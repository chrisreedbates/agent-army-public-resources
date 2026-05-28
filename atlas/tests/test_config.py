from atlas.config import Config


def test_config_from_env_reads_expected_values(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ATLAS_OWNER_NAME", "Ada")
    monkeypatch.setenv("ATLAS_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("ATLAS_MAX_TURNS", "7")

    config = Config.from_env()

    assert config.anthropic_api_key == "test-key"
    assert config.owner_name == "Ada"
    assert config.state_dir == str(tmp_path)
    assert config.max_turns == 7


def test_config_validate_requires_anthropic_key():
    assert Config().validate() == ["ANTHROPIC_API_KEY is required"]
