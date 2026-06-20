"""settings.py — настройки пользователя (мультитенант): Anthropic-ключ, Telegram, источники."""
from . import engine, classifier, tg_session, tg_bot


def _session(uid):
    return f"sessions/u{uid}"


def mask(s):
    return (s[:4] + "…" + s[-4:]) if s and len(s) > 10 else ("•••••" if s else "")


def status(uid):
    cfg = engine.get_config(uid)
    tg = cfg.get("tg", {})
    dg = cfg.get("digest", {})
    return {
        "claude": bool(cfg.get("anthropic_key")),
        "claude_masked": mask(cfg.get("anthropic_key", "")),
        "telegram": {
            "creds": bool(tg.get("api_id") and tg.get("api_hash")),
            "connected": tg_session.session_exists(_session(uid)),
            "chats": tg.get("chats", []),
        },
        "digest": {
            "configured": bool(dg.get("bot_token") and dg.get("chat_id")),
            "enabled": bool(dg.get("enabled")),
            "bot_username": dg.get("bot_username", ""),
            "chat_name": dg.get("chat_name", ""),
            "token_masked": mask(dg.get("bot_token", "")),
            "hour": dg.get("hour", 9),
            "tz_offset": dg.get("tz_offset", 4),
            "min_strength": dg.get("min_strength", 4),
        },
    }


def verify_digest_bot(uid, token):
    r = tg_bot.verify((token or "").strip())
    if r.get("ok"):
        engine.set_digest(uid, {"bot_token": token.strip(), "bot_username": r.get("username", "")})
    return r


def detect_digest_chat(uid):
    cfg = engine.get_config(uid); dg = cfg.get("digest", {})
    if not dg.get("bot_token"):
        return {"ok": False, "error": "Сначала впиши и проверь токен бота"}
    r = tg_bot.detect_chat(dg["bot_token"])
    if r.get("ok"):
        engine.set_digest(uid, {"chat_id": r["chat_id"], "chat_name": r.get("name", "")})
    return r


def save_digest(uid, d):
    dg = engine.set_digest(uid, d or {})
    return {"ok": True, "configured": bool(dg.get("bot_token") and dg.get("chat_id")),
            "enabled": bool(dg.get("enabled"))}


def test_digest(uid):
    return engine.send_digest(uid, force=True)


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
