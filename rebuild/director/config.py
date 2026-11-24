"""config.yaml 로더.

원본(env_utils.root_config)은 dict를 그대로 돌려주고 곳곳에서 .get(key, default)로 읽었습니다.
그래서 키 이름을 잘못 적어도 아무 오류 없이 기본값이 쓰였습니다.
여기서는 pydantic 모델로 검증해서, 오타가 있으면 시작할 때 바로 오류를 냅니다.
"""
from pathlib import Path
from typing import Literal, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field

Provider = Literal["claude", "codex", "mock"]


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")   # 모르는 키 = 오타로 보고 거부


class RoleConfig(_Section):
    provider: Provider
    executable: Optional[str] = None


class Timeouts(_Section):
    head: float = Field(300, gt=0)
    builder: float = Field(600, gt=0)
    reviewer: float = Field(300, gt=0)
    no_output: Optional[float] = Field(180, gt=0)


class Safety(_Section):
    max_files_changed: int = Field(15, ge=1)
    max_diff_lines: int = Field(1500, ge=1)


class Verification(_Section):
    test_command: Optional[Union[str, list]] = None


class DirectorConfig(_Section):
    head: RoleConfig = RoleConfig(provider="claude")
    builder: RoleConfig = RoleConfig(provider="codex")
    reviewer: RoleConfig = RoleConfig(provider="claude")
    timeouts: Timeouts = Timeouts()
    safety: Safety = Safety()
    verification: Verification = Verification()


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


class ConfigError(Exception):
    pass


def load_config(path: Optional[Union[str, Path]] = None) -> DirectorConfig:
    """설정 파일을 읽어 검증합니다. 파일이 없으면 기본값, 형식이 틀리면 ConfigError."""
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    if not p.exists():
        return DirectorConfig()
    try:
        # 윈도우 기본 인코딩(cp949)에 의존하지 않도록 utf-8을 명시합니다.
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"{p}: YAML 문법 오류: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"{p}: 최상위는 key: value 형태여야 합니다")
    try:
        return DirectorConfig.model_validate(raw)
    except Exception as e:
        raise ConfigError(f"{p}: 설정 값 오류:\n{e}") from e
