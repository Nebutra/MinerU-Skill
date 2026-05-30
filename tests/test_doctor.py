"""Tests for the --doctor environment self-check."""

import json

import mineru


def test_check_token_invalid(monkeypatch):
    monkeypatch.setattr(mineru, "_http", lambda *a, **k: (
        200, json.dumps({"success": False, "msgCode": "A0202", "msg": "auth failed"}).encode()))
    ok, detail = mineru._check_token("bad")
    assert ok is False and "A0202" in detail


def test_check_token_accepted_on_param_error(monkeypatch):
    monkeypatch.setattr(mineru, "_http", lambda *a, **k: (
        200, json.dumps({"code": -500, "msg": "param error"}).encode()))
    ok, _detail = mineru._check_token("good")
    assert ok is True


def test_doctor_json_healthy(monkeypatch, capsys):
    monkeypatch.setattr(mineru, "_http", lambda *a, **k: (200, b""))
    monkeypatch.delenv("MINERU_TOKEN", raising=False)
    code = mineru._doctor(as_json=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["network"]["ok"] is True
    assert payload["token"]["ok"] is True  # unset -> fine (Agent API is token-free)
    assert "optional_extras" in payload and "sinks" in payload
    assert code == 0 and payload["healthy"] is True


def test_doctor_unhealthy_when_network_down(monkeypatch, capsys):
    monkeypatch.setattr(mineru, "_http", lambda *a, **k: (_ for _ in ()).throw(OSError("no net")))
    monkeypatch.delenv("MINERU_TOKEN", raising=False)
    code = mineru._doctor(as_json=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["network"]["ok"] is False
    assert code == 1 and payload["healthy"] is False


def test_doctor_reports_invalid_token(monkeypatch, capsys):
    def fake_http(method, url, *, headers=None, data=None, timeout=60):
        if url.rstrip("/") == "https://mineru.net":
            return 200, b""
        return 200, json.dumps({"success": False, "msgCode": "A0211"}).encode()

    monkeypatch.setattr(mineru, "_http", fake_http)
    monkeypatch.setenv("MINERU_TOKEN", "expired-token")
    code = mineru._doctor(as_json=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["token"]["ok"] is False and "A0211" in payload["token"]["detail"]
    assert code == 1


def test_cli_doctor(monkeypatch, capsys):
    monkeypatch.setattr(mineru, "_http", lambda *a, **k: (200, b""))
    monkeypatch.delenv("MINERU_TOKEN", raising=False)
    code = mineru.main(["--doctor", "--json"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["healthy"] is True
