from atlas.cli import main


def test_version_command(capsys):
    assert main(["version"]) == 0
    assert capsys.readouterr().out.strip() == "atlas 0.1.0"


def test_docs_works_without_api_key(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert main(["--state-dir", str(tmp_path), "docs"]) == 0
    assert "No documents saved yet." in capsys.readouterr().out
