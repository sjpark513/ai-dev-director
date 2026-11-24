import pytest

from director.config import ConfigError, DirectorConfig, load_config


def test_bundled_config_loads():
    cfg = load_config()
    assert cfg.head.provider == "claude" and cfg.builder.provider == "codex"
    assert cfg.timeouts.no_output == 180


def test_missing_file_gives_defaults(tmp_path):
    assert load_config(tmp_path / "none.yaml") == DirectorConfig()


def test_typo_is_rejected(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("timeouts:\n  bulider: 10\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="bulider"):
        load_config(p)


def test_unknown_provider_rejected(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("head:\n  provider: gpt\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(p)


def test_korean_comment_utf8(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("# 한글 주석\nsafety:\n  max_files_changed: 3\n", encoding="utf-8")
    assert load_config(p).safety.max_files_changed == 3


def test_yaml_syntax_error(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("head: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(p)
