import json

import pytest

from gateway.cli import main


def test_cli_tenant_create_list_revoke_and_seed(tmp_path, capsys):
    prefix = ["--database", str(tmp_path / "db")]
    main([*prefix, "tenant", "alice", "--budget", "1000"])
    main([*prefix, "create-key", "alice"])
    key = json.loads(capsys.readouterr().out)
    main([*prefix, "list-keys"])
    listing = capsys.readouterr().out
    assert key["api_key"] not in listing and key["key_id"] in listing
    main([*prefix, "revoke-key", key["key_id"]])
    main([*prefix, "seed-demo", "--directory", str(tmp_path / "data")])
    assert (tmp_path / "data/demo.key").exists()
    assert "gw_" not in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main([*prefix, "seed-demo", "--directory", str(tmp_path / "data")])
    with pytest.raises(SystemExit):
        main([*prefix, "create-key", "missing"])


def test_server_commands(monkeypatch):
    calls = []
    monkeypatch.setattr("gateway.cli.uvicorn.run", lambda *a, **kw: calls.append((a, kw)))
    main(["--database", "custom.db", "serve", "--demo"])
    from gateway.settings import Settings

    assert Settings().database == "custom.db"
    assert calls[-1][1]["factory"] is True
    main(["mock"])
    assert calls[-1][1]["factory"] is False
    monkeypatch.delenv("GATEWAY_ENVIRONMENT")
    monkeypatch.delenv("GATEWAY_QUOTA_BACKEND")
    monkeypatch.delenv("GATEWAY_IDENTITY_BACKEND")
    monkeypatch.delenv("GATEWAY_DATABASE")
