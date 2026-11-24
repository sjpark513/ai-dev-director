"""모든 테스트 공통 설정: 실제 AI CLI 호출을 막고, 테스트용 파이썬 경로를 준비합니다."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _testing_mode(monkeypatch):
    monkeypatch.setenv("DIRECTOR_TESTING", "1")


@pytest.fixture
def py():
    """현재 테스트를 돌리는 파이썬. 'python'이라고 쓰면 윈도우/맥에서 다른 파이썬이 잡힐 수 있습니다."""
    return sys.executable
