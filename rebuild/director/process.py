"""AI CLI와 테스트 명령을 안전하게 실행하는 실행기.

원본: core/process_runner.py (ProcessTreeRunner)

지켜야 할 것:
  1. shell=False — 프롬프트나 경로가 셸 명령으로 해석되지 않게 합니다.
  2. 출력은 별도 스레드에서 계속 읽습니다 — 파이프 버퍼(보통 64KB)가 차면 자식이 멈추기 때문입니다.
  3. 타임아웃이 나면 자식뿐 아니라 손자 프로세스까지 모두 종료합니다.
     (CLI는 node, 셸, 테스트 러너 등을 다시 띄웁니다. 부모만 죽이면 고아 프로세스가 남아 계속 돕니다.)
  4. 출력이 오래 끊기면(no_output_timeout) 멈춘 것으로 보고 종료합니다.

원본과 달라진 점(학습 포인트):
  - stdin을 출력 읽기 스레드를 띄운 "뒤에", 별도 스레드에서 씁니다. 원본은 읽기 전에 stdin을 다 써서,
    큰 프롬프트를 보내는 동안 자식이 출력을 많이 내면 서로 기다리는 교착(deadlock)이 생길 수 있었습니다.
  - 출력을 줄(readline)이 아니라 바이트 덩어리로 읽습니다. 줄바꿈 없는 진행 표시도 "출력 있음"으로 칩니다.
    바이트는 마지막에 한 번에 utf-8로 디코딩해서 한글 글자가 덩어리 경계에서 깨지지 않게 합니다.
  - 맥/리눅스는 새 세션(프로세스 그룹)으로 띄워 그룹 전체를 한 번에 종료합니다.
"""
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

import psutil

from director.env import sanitized_env

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
REAL_CLI_NAMES = {"claude", "codex", "agy"}
_POLL_INTERVAL = 0.05


@dataclass
class ProcessResult:
    argv: List[str]
    exit_code: Optional[int]
    stdout: str
    stderr: str
    duration_sec: float
    pid: Optional[int]
    stop_reason: Optional[str] = None   # None(정상 종료) | "HARD_TIMEOUT" | "NO_OUTPUT_TIMEOUT" | "STOPPED"
    survivors: List[int] = field(default_factory=list)   # 종료에 실패한 pid (비어 있어야 정상)

    @property
    def timed_out(self) -> bool:
        return self.stop_reason in ("HARD_TIMEOUT", "NO_OUTPUT_TIMEOUT")

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and self.stop_reason is None


class RealCliCallBlocked(RuntimeError):
    """테스트 중(DIRECTOR_TESTING=1)에 실제 AI CLI를 부르려 하면 막습니다. 구독 한도를 지키기 위한 안전장치."""


# 지금 돌고 있는 프로세스 목록. "작업 정지" 버튼(kill_active)이 이 목록을 씁니다.
_ACTIVE: Dict[int, str] = {}
_ACTIVE_LOCK = threading.Lock()


def active_processes() -> Dict[int, str]:
    with _ACTIVE_LOCK:
        return dict(_ACTIVE)


# [핵심] 직접 확인할 함수 — 멈춘 CLI를 확실히 끝내는 유일한 경로입니다.
def kill_tree(pid: int, wait: float = 3.0) -> List[int]:
    """pid와 그 모든 자손을 종료합니다. 끝까지 살아남은 pid 목록을 돌려줍니다(정상이면 빈 목록).

    순서가 중요합니다. 부모를 먼저 죽이면 자식이 고아가 되어 부모-자식 관계로는 더 이상 찾을 수 없으므로,
    먼저 자손 목록을 "찍어 두고(snapshot)" 그다음 종료합니다.
    """
    try:
        root = psutil.Process(pid)
        procs = root.children(recursive=True) + [root]
    except psutil.NoSuchProcess:
        return []

    if IS_WINDOWS:
        # 윈도우: taskkill /T 가 트리 전체를 한 번에 정리합니다. 실패해도 아래 psutil 정리가 이어받습니다.
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning("taskkill failed for %s: %s", pid, e)
    else:
        # 맥/리눅스: run()에서 start_new_session=True로 띄웠으므로 pid가 곧 프로세스 그룹 id입니다.
        # 그룹 종료는 이미 고아가 된 손자까지 잡아냅니다.
        try:
            if os.getpgid(pid) == pid:
                os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    for p in procs:
        try:
            p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    # 주의: psutil.wait_procs()는 쓰지 않습니다. 그것은 우리 직속 자식을 waitpid로 "거둬(reap)" 버려서,
    # subprocess.Popen이 종료 코드를 못 받고 0(정상 종료)으로 잘못 기록하게 만듭니다.
    # 그래서 '좀비(종료됐지만 아직 안 거둔 상태)도 죽은 것으로 본다'는 기준으로 직접 기다립니다.
    deadline = time.monotonic() + wait
    alive = procs
    while alive and time.monotonic() < deadline:
        alive = [p for p in alive if _is_alive(p)]
        if alive:
            time.sleep(_POLL_INTERVAL)
    return [p.pid for p in alive]


def _is_alive(p: "psutil.Process") -> bool:
    try:
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def kill_active() -> List[int]:
    """실행 중인 모든 CLI 프로세스 트리를 종료합니다(작업 정지). 종료한 pid 목록을 돌려줍니다."""
    killed = []
    for pid in active_processes():
        if not kill_tree(pid):
            killed.append(pid)
    return killed


def _is_real_cli(argv0: str) -> bool:
    # 윈도우 경로(C:\tools\claude.cmd)도 맥에서 판별할 수 있게 두 구분자를 모두 처리합니다.
    name = re.split(r"[\\/]", argv0)[-1].lower()
    stem, dot, ext = name.rpartition(".")
    if dot and ext in ("exe", "cmd", "bat", "ps1"):
        name = stem
    return name in REAL_CLI_NAMES


def _drain(pipe, chunks: List[bytes], last_output: List[float]) -> None:
    """파이프가 닫힐 때까지 바이트 덩어리로 읽습니다. 읽을 때마다 '마지막 출력 시각'을 갱신합니다."""
    try:
        while True:
            data = pipe.read1(65536) if hasattr(pipe, "read1") else pipe.read(65536)
            if not data:
                break
            chunks.append(data)
            last_output[0] = time.monotonic()
    except (OSError, ValueError):
        pass
    finally:
        try:
            pipe.close()
        except OSError:
            pass


def _feed(pipe, data: bytes) -> None:
    try:
        pipe.write(data)
    except (BrokenPipeError, OSError):
        pass   # 자식이 stdin을 다 읽기 전에 끝난 경우. 결과는 exit_code로 판단합니다.
    finally:
        try:
            pipe.close()
        except OSError:
            pass


def _decode(chunks: List[bytes]) -> str:
    return b"".join(chunks).decode("utf-8", errors="replace")


# [핵심] 직접 확인할 함수 — 모든 외부 실행이 이 한 곳을 지납니다.
def run(
    argv: Sequence[str],
    *,
    cwd: Optional[str] = None,
    timeout: float = 300.0,
    no_output_timeout: Optional[float] = None,
    stdin_data: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> ProcessResult:
    """명령을 실행하고 끝나거나 타임아웃이 날 때까지 기다립니다.

    argv: ["claude", "--print", ...] 처럼 리스트로. 문자열 하나로 넘기지 않습니다(shell=False).
    stdin_data: 긴 프롬프트는 명령줄 인자 대신 stdin으로 보냅니다(윈도우 명령줄 길이 제한 약 32K자, 인용 문제 회피).
    env: 기본값은 과금 변수를 지운 환경(sanitized_env).
    should_stop: True를 돌려주면 즉시 종료합니다(사용자의 '작업 정지').
    """
    argv = [str(a) for a in argv]
    if not argv:
        raise ValueError("argv is empty")
    if os.environ.get("DIRECTOR_TESTING") == "1" and _is_real_cli(argv[0]):
        raise RealCliCallBlocked(f"real CLI call blocked during tests: {argv[0]}")

    popen_kwargs = {}
    if IS_WINDOWS:
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True   # 새 프로세스 그룹 → kill_tree가 그룹째 종료

    start = time.monotonic()
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        env=sanitized_env() if env is None else env,
        shell=False,
        stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **popen_kwargs,
    )
    with _ACTIVE_LOCK:
        _ACTIVE[proc.pid] = argv[0]

    last_output = [start]
    out_chunks: List[bytes] = []
    err_chunks: List[bytes] = []
    threads = [
        threading.Thread(target=_drain, args=(proc.stdout, out_chunks, last_output), daemon=True),
        threading.Thread(target=_drain, args=(proc.stderr, err_chunks, last_output), daemon=True),
    ]
    if stdin_data is not None:
        threads.append(threading.Thread(target=_feed, args=(proc.stdin, stdin_data.encode("utf-8")), daemon=True))
    for t in threads:
        t.start()

    reason = None
    try:
        while proc.poll() is None:
            now = time.monotonic()
            if now - start >= timeout:
                reason = "HARD_TIMEOUT"
            elif no_output_timeout and now - last_output[0] >= no_output_timeout:
                reason = "NO_OUTPUT_TIMEOUT"
            elif should_stop is not None and should_stop():
                reason = "STOPPED"
            if reason:
                break
            time.sleep(_POLL_INTERVAL)
    finally:
        survivors: List[int] = []
        if reason or proc.poll() is None:
            # 타임아웃·정지, 또는 예외(Ctrl+C 등)로 빠져나온 경우: 남은 트리를 정리합니다.
            logger.warning("terminating %s (pid %s): %s", argv[0], proc.pid, reason or "interrupted")
            survivors = kill_tree(proc.pid)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                survivors = survivors or [proc.pid]
        with _ACTIVE_LOCK:
            _ACTIVE.pop(proc.pid, None)
        # 손자 프로세스가 파이프를 물고 있으면 읽기 스레드가 끝나지 않을 수 있어, 기다리는 시간을 제한합니다.
        for t in threads:
            t.join(timeout=2.0)

    return ProcessResult(
        argv=argv,
        exit_code=proc.returncode,
        stdout=_decode(out_chunks),
        stderr=_decode(err_chunks),
        duration_sec=round(time.monotonic() - start, 3),
        pid=proc.pid,
        stop_reason=reason,
        survivors=survivors,
    )
