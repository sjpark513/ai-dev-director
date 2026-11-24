"""프로세스 실행기 테스트. 모두 현재 파이썬(sys.executable)으로 자식 프로세스를 만들어 윈도우/맥 공통으로 돕니다."""
import threading
import time

import psutil
import pytest

from director import process
from director.process import RealCliCallBlocked, active_processes, kill_active, run


def alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def wait_dead(pid: int, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.05)
    return False


def test_stdout_stderr_exit_code(py):
    r = run([py, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"], timeout=30)
    assert r.exit_code == 3 and r.stdout.strip() == "out" and r.stderr.strip() == "err"
    assert not r.ok and r.stop_reason is None and not r.timed_out


def test_korean_output_is_utf8(py):
    r = run([py, "-c", "print('한글 출력 ✓')"], timeout=30)
    assert r.ok and "한글 출력 ✓" in r.stdout


def test_large_stdin_while_child_floods_stdout(py):
    # 자식이 stdin을 읽기 전에 1MB를 먼저 출력합니다. stdin을 먼저 다 쓰려는 구현이면 여기서 교착됩니다.
    code = "import sys; sys.stdout.write('x' * 1_000_000); sys.stdout.flush(); print(len(sys.stdin.read()))"
    data = "가" * 700_000   # utf-8로 약 2MB
    r = run([py, "-c", code], stdin_data=data, timeout=60)
    assert r.ok, r.stderr
    assert r.stdout.endswith(f"{len(data)}\n") or r.stdout.rstrip().endswith(str(len(data)))
    assert r.stdout.count("x") == 1_000_000


def test_hard_timeout_kills_grandchild(py, tmp_path):
    pid_file = tmp_path / "grandchild.pid"
    code = (
        "import subprocess, sys, time\n"
        f"g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open(r'{pid_file}', 'w').write(str(g.pid))\n"
        "time.sleep(60)\n"
    )
    r = run([py, "-c", code], timeout=2)
    assert r.stop_reason == "HARD_TIMEOUT" and r.timed_out
    assert r.exit_code not in (0, None)   # 강제 종료가 '정상 종료(0)'로 기록되면 안 됩니다
    assert r.survivors == []
    assert r.duration_sec < 10
    assert wait_dead(int(pid_file.read_text())), "grandchild survived"
    assert not alive(r.pid)


def test_no_output_timeout(py):
    r = run([py, "-c", "import time; time.sleep(30)"], timeout=30, no_output_timeout=1)
    assert r.stop_reason == "NO_OUTPUT_TIMEOUT"


def test_progress_without_newline_counts_as_output(py):
    code = "import sys, time\nfor _ in range(8):\n    sys.stdout.write('.'); sys.stdout.flush(); time.sleep(0.25)\n"
    r = run([py, "-c", code], timeout=30, no_output_timeout=1)
    assert r.ok and r.stdout == "........"


def test_should_stop(py):
    started = time.monotonic()
    r = run([py, "-c", "import time; time.sleep(30)"], timeout=30,
            should_stop=lambda: time.monotonic() - started > 0.5)
    assert r.stop_reason == "STOPPED" and not r.timed_out


def test_env_is_sanitized_by_default(py, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    r = run([py, "-c", "import os; print(os.environ.get('OPENAI_API_KEY', 'NONE'))"], timeout=30)
    assert r.stdout.strip() == "NONE"


@pytest.mark.parametrize("exe", ["claude", "/usr/local/bin/codex", r"C:\tools\claude.cmd", "agy.exe"])
def test_real_cli_blocked_in_tests(exe):
    with pytest.raises(RealCliCallBlocked):
        run([exe, "--version"])


def test_kill_active_stops_running_process(py):
    box = {}
    t = threading.Thread(target=lambda: box.setdefault("r", run([py, "-c", "import time; time.sleep(30)"], timeout=30)))
    t.start()
    deadline = time.monotonic() + 10
    while not active_processes() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert active_processes()
    assert kill_active()
    t.join(timeout=10)
    assert box["r"].exit_code not in (0, None)   # 강제 종료 = 0이 아닌 코드
    assert active_processes() == {}


def test_missing_executable_raises():
    with pytest.raises(FileNotFoundError):
        run(["definitely-not-a-real-program-xyz"], timeout=5)
    assert process.active_processes() == {}
