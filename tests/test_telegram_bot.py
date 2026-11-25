from fastapi.testclient import TestClient

from app.web import telegram_bot


def _client(monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "webhook_secret", "s3cret")
    monkeypatch.setattr(s, "telegram_chat_id", "111")
    sent = []
    monkeypatch.setattr(telegram_bot, "send_message", lambda text, *a, **k: sent.append(text) or True)
    from app.web.main import app

    return TestClient(app), sent


def _update(chat_id, text):
    return {"update_id": 1, "message": {"chat": {"id": chat_id}, "text": text}}


def test_command_parsing():
    assert telegram_bot._command("run now") == "run"
    assert telegram_bot._command("/run@MyBot") == "run"
    assert telegram_bot._command("Status") == "status"
    assert telegram_bot._command("hello") == "help"


def test_wrong_secret_is_ignored(monkeypatch):
    client, sent = _client(monkeypatch)
    r = client.post("/telegram/webhook", json=_update(111, "status"),
                    headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"})
    assert r.status_code == 200 and sent == []


def test_other_chat_is_ignored(monkeypatch):
    client, sent = _client(monkeypatch)
    client.post("/telegram/webhook", json=_update(999, "run now"),
                headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"})
    assert sent == []


def test_run_now_starts_one_scan(monkeypatch):
    client, sent = _client(monkeypatch)
    started = []
    monkeypatch.setattr(telegram_bot, "start_scan", lambda **k: (started.append(1) or len(started) == 1))
    h = {"X-Telegram-Bot-Api-Secret-Token": "s3cret"}
    client.post("/telegram/webhook", json=_update(111, "run now"), headers=h)
    client.post("/telegram/webhook", json=_update(111, "run now"), headers=h)
    assert "Searching" in sent[0] and "running right now" in sent[1]


def test_cron_needs_the_key(monkeypatch):
    client, _ = _client(monkeypatch)
    calls = []
    monkeypatch.setattr(telegram_bot, "start_scan", lambda **k: calls.append(k) or True)
    assert client.get("/cron/scan?key=wrong").json() == {"ok": False}
    assert client.get("/cron/scan?key=s3cret").json() == {"ok": True, "started": True}
    assert calls == [{"notify": False}]


def test_scan_lock_is_exclusive():
    from app.db import init_db, release_lock, try_lock

    init_db()
    release_lock("test")
    assert try_lock("test", 60) is True
    assert try_lock("test", 60) is False
    release_lock("test")
    assert try_lock("test", 60) is True
    release_lock("test")
