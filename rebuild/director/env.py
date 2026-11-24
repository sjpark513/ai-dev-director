"""CLI 실행 환경: 과금 변수 제거와 CLI 실행 파일 찾기.

원본: core/env_utils.py
"""
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional

# 구독 로그인 대신 종량제/다른 과금 경로로 CLI를 돌려 버리는 변수들.
# 목록이 아니라 "규칙"(모든 *_API_KEY) + 알려진 토큰·엔드포인트 변수로 막습니다.
# (원본도 처음에는 키 5개만 적은 목록이었다가 CODEX_API_KEY 등이 새는 문제로 규칙으로 바꿨습니다.)
BILLING_VARIABLES = {
    "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_BEDROCK_BASE_URL", "ANTHROPIC_VERTEX_BASE_URL",
    "ANTHROPIC_VERTEX_PROJECT_ID", "ANTHROPIC_FOUNDRY_RESOURCE", "ANTHROPIC_FOUNDRY_BASE_URL",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "AWS_BEARER_TOKEN_BEDROCK",
    "OPENAI_BASE_URL", "OPENAI_API_BASE", "OPENAI_ORG_ID", "OPENAI_ORGANIZATION",
    "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_GENAI_USE_GCA", "GOOGLE_GEMINI_BASE_URL", "GOOGLE_VERTEX_BASE_URL",
}


def is_billing_variable(name: str) -> bool:
    upper = (name or "").upper()
    return upper.endswith("_API_KEY") or upper.endswith("_API_KEYS") or upper in BILLING_VARIABLES


# [핵심] 직접 확인할 함수 — 모든 CLI 호출과 테스트 명령은 이 환경으로만 실행됩니다.
def sanitized_env(base: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """과금 관련 변수를 지운 환경변수 사본을 돌려줍니다. 원본 환경(os.environ)은 바꾸지 않습니다.

    한계: CLI 자체를 API 키로 로그인해 둔 경우(예: codex login --with-api-key)는 여기서 막을 수 없습니다.
    """
    env = dict(os.environ if base is None else base)
    for name in list(env):
        if is_billing_variable(name):
            del env[name]
    # 자식 파이썬 프로세스의 출력도 utf-8로 고정합니다(한국어 윈도우의 cp949 문제 예방).
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _candidate_dirs() -> List[Path]:
    """PATH에 없을 때 추가로 찾아볼 표준 설치 위치. OS마다 다릅니다."""
    home = Path.home()
    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", home / "AppData/Roaming"))
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
        return [appdata / "npm", local / "Programs", home / ".local/bin"]
    # macOS: 공식 설치 스크립트 → ~/.local/bin, Homebrew(애플 실리콘) → /opt/homebrew/bin, npm -g → /usr/local/bin
    return [home / ".local/bin", Path("/opt/homebrew/bin"), Path("/usr/local/bin"), home / ".npm-global/bin"]


def _windows_names(name: str) -> List[str]:
    """윈도우에서는 확장자까지 붙여야 shell=False로 실행할 수 있습니다. .exe를 .cmd보다 먼저 찾습니다."""
    if Path(name).suffix:
        return [name]
    return [name + ext for ext in (".exe", ".cmd", ".bat")]


def resolve_cli(name: str, extra_dirs: Iterable[Path] = ()) -> Optional[str]:
    """CLI 실행 파일의 절대 경로를 찾습니다. 못 찾으면 None.

    1) PATH (shutil.which는 윈도우에서 PATHEXT를 보고 claude.cmd 같은 확장자도 찾아 줍니다)
    2) OS별 표준 설치 위치
    """
    found = shutil.which(name)
    if found:
        return str(Path(found).resolve())
    names = _windows_names(name) if sys.platform == "win32" else [name]
    for directory in [*extra_dirs, *_candidate_dirs()]:
        for candidate in names:
            p = Path(directory) / candidate
            if p.is_file() and (sys.platform == "win32" or os.access(p, os.X_OK)):
                return str(p.resolve())
    return None
