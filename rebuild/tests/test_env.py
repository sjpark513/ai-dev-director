import os
import stat
import sys

from director.env import is_billing_variable, resolve_cli, sanitized_env


def test_billing_rule_covers_unlisted_keys():
    for name in ["OPENAI_API_KEY", "CODEX_API_KEY", "some_new_api_key", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK"]:
        assert is_billing_variable(name), name
    for name in ["PATH", "HOME", "API_KEY_HINT", "USERPROFILE"]:
        assert not is_billing_variable(name), name


def test_sanitized_env_strips_and_keeps(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://x")
    env = sanitized_env()
    assert "OPENAI_API_KEY" not in env and "ANTHROPIC_BASE_URL" not in env
    assert env["PATH"] == os.environ["PATH"]
    assert os.environ["OPENAI_API_KEY"] == "sk-test"   # 원본 환경은 그대로


def test_resolve_cli_from_path():
    assert resolve_cli("python3" if sys.platform != "win32" else "python")


def test_resolve_cli_missing():
    assert resolve_cli("definitely-not-a-real-cli-xyz") is None


def test_resolve_cli_extra_dir(tmp_path):
    name = "fakecli"
    if sys.platform == "win32":
        (tmp_path / "fakecli.cmd").write_text("@echo off\n", encoding="utf-8")
        expected = "fakecli.cmd"
    else:
        f = tmp_path / name
        f.write_text("#!/bin/sh\n", encoding="utf-8")
        f.chmod(f.stat().st_mode | stat.S_IXUSR)
        expected = name
    found = resolve_cli(name, extra_dirs=[tmp_path])
    assert found and found.lower().endswith(expected)
