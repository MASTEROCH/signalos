"""settings.py — настройки пользователя (мультитенант): Anthropic-ключ, Telegram, источники."""
from . import engine, classifier, tg_session


def _session(uid):
    return f"sessions/u{uid}"


def mask(s):
    return (s[:4] + "…" + s[-4:]) if s and len(s) > 10 else ("•••••" if s else "")


def status(uid):
    cfg = engine.get_config(uid)
    tg = cfg.get("tg", {})
    return {
        "claude": bool(cfg.get("anthropic_key")),
        "claude_masked": mask(cfg.get("anthropic_key", "")),
        "telegram": {
            "creds": bool(tg.get("api_id") and tg.get("api_hash")),
            "connected": tg_session.session_exists(_session(uid)),
            "chats": tg.get("chats", []),
        },
    }


def save_claude(uid, key):
    cfg = engine.get_config(uid)
    cfg["anthropic_key"] = key.strip()
    engine.save_config(uid, cfg)
    res = classifier._anthropic(classifier.CLASSIFY_MODEL, "Reply: ok", "ping", 5, key.strip())
    valid = res is not None
    return {"ok": True, "valid": valid,
            "msg": "Ключ работает — Claude включён" if valid
                   else "Ключ сохранён, но проверка не прошла (опечатка или нет средств на балансе)"}


def save_telegram(uid, api_id, api_hash, phone, chats):
    cfg = engine.get_config(uid)
    tg = cfg.setdefault("tg", {})
    if api_id: tg["api_id"] = str(api_id).strip()
    if api_hash: tg["api_hash"] = api_hash.strip()
    if phone: tg["phone"] = phone.strip()
    tg["chats"] = [c.strip().lstrip("@") for c in (chats or []) if c.strip()]
    connected = tg_session.session_exists(_session(uid))
    for s in cfg.get("sources", []):
        if s["id"] == "telegram":
            s["enabled"] = bool(connected and tg["chats"])
    engine.save_config(uid, cfg)
    return {"ok": True, "need_login": not connected, "chats": tg["chats"]}


def send_code(uid):
    cfg = engine.get_config(uid); tg = cfg.get("tg", {})
    if not (tg.get("api_id") and tg.get("api_hash") and tg.get("phone")):
        return {"error": "Сначала впиши api_id, api_hash и телефон"}
    if not tg_session.available():
        return {"error": "Telethon не установлен (запусти через ./run.sh)"}
    try:
        return tg_session.send_code(tg["api_id"], tg["api_hash"], tg["phone"], _session(uid))
    except Exception as e:
        return {"error": str(e)}


def sign_in(uid, code=None, password=None):
    try:
        r = (tg_session.sign_in_password(password, _session(uid)) if password
             else tg_session.sign_in_code(code, _session(uid)))
        if r.get("connected"):
            cfg = engine.get_config(uid)
            for s in cfg.get("sources", []):
                if s["id"] == "telegram":
                    s["enabled"] = bool(cfg.get("tg", {}).get("chats"))
            engine.save_config(uid, cfg)
        return r
    except Exception as e:
        return {"error": str(e)}


def toggle_source(uid, sid, enabled):
    cfg = engine.get_config(uid)
    for s in cfg.get("sources", []):
        if s["id"] == sid:
            s["enabled"] = bool(enabled)
    engine.save_config(uid, cfg)
    return {"ok": True}
