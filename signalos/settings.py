"""
settings.py — управление ключами из интерфейса (без терминала).
Пишет/читает .env, включает Claude на лету, проверяет Telegram-подключение.
"""
import os, json, asyncio

ENV_PATH = os.environ.get("SIGNALOS_ENV", ".env")


# ---------- .env ----------
def read_env():
    data = {}
    if os.path.exists(ENV_PATH):
        for line in open(ENV_PATH, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()
    return data


def set_env(updates):
    """Обновляет .env и текущее окружение процесса (применяется сразу, без рестарта)."""
    data = read_env()
    data.update(updates)
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("# SignalOS — ключи (создано из интерфейса)\n")
        for k, v in data.items():
            f.write(f"{k}={v}\n")
    for k, v in updates.items():
        os.environ[k] = v


def mask(s):
    if not s:
        return ""
    return (s[:4] + "…" + s[-4:]) if len(s) > 10 else "•••••"


# ---------- статус ----------
def status():
    env = read_env()
    return {
        "claude": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "claude_masked": mask(os.environ.get("ANTHROPIC_API_KEY", "")),
        "telegram": {
            "creds": bool(os.environ.get("TELEGRAM_API_ID") and os.environ.get("TELEGRAM_API_HASH")),
            "connected": _session_exists(),
            "chats": _tg_chats(),
        },
    }


# ---------- Claude ----------
def save_claude(key):
    from . import classifier
    set_env({"ANTHROPIC_API_KEY": key.strip()})
    # живая проверка одним коротким запросом
    res = classifier._anthropic(classifier.CLASSIFY_MODEL, "Reply with: ok", "ping", 5)
    valid = res is not None
    return {"ok": True, "valid": valid,
            "msg": "Ключ работает — Claude включён ✓" if valid
                   else "Ключ сохранён, но проверка не прошла (опечатка или нет средств на балансе)"}


# ---------- Telegram ----------
def save_telegram(api_id, api_hash, phone, chats):
    upd = {}
    if api_id:   upd["TELEGRAM_API_ID"] = str(api_id).strip()
    if api_hash: upd["TELEGRAM_API_HASH"] = api_hash.strip()
    if phone:    upd["TELEGRAM_PHONE"] = phone.strip()
    if upd:
        set_env(upd)
    chat_list = [c.strip().lstrip("@") for c in (chats or []) if c.strip()]
    _set_tg_chats(chat_list, enable=_session_exists())
    return {"ok": True, "need_login": not _session_exists(), "chats": chat_list}


def check_telegram():
    api_id = int(os.environ.get("TELEGRAM_API_ID", "0") or 0)
    api_hash = os.environ.get("TELEGRAM_API_HASH", "")
    if not (api_id and api_hash):
        return {"connected": False, "error": "Сначала впиши api_id и api_hash"}
    try:
        from telethon import TelegramClient  # noqa
    except ImportError:
        return {"connected": False, "error": "Установи библиотеку: pip install telethon"}
    try:
        ok, name = asyncio.run(_tg_probe(api_id, api_hash))
    except Exception as e:
        return {"connected": False, "error": f"Не удалось подключиться: {e}"}
    if ok:
        _set_tg_chats(_tg_chats(), enable=True)
    return {"connected": ok, "name": name,
            "error": "" if ok else "Сессии нет — выполни в терминале: python3 -m signalos.tg_login"}


async def _tg_probe(api_id, api_hash):
    from telethon import TelegramClient
    c = TelegramClient("signalos", api_id, api_hash)
    await c.connect()
    try:
        ok = await c.is_user_authorized()
        me = await c.get_me() if ok else None
        return ok, (me.first_name if me else None)
    finally:
        await c.disconnect()


def _session_exists():
    return os.path.exists("signalos.session")


# ---------- доступ к config (источник telegram) ----------
def _cfg_path():
    from . import engine
    return engine.CONFIG if os.path.exists(engine.CONFIG) else None


def _load_cfg():
    p = _cfg_path()
    return json.load(open(p, encoding="utf-8")) if p else None


def _tg_chats():
    cfg = _load_cfg()
    if not cfg:
        return []
    for s in cfg.get("sources", []):
        if s["id"] == "telegram":
            return s.get("chats", [])
    return []


def _set_tg_chats(chats, enable):
    from . import engine
    cfg = engine.load_config()
    found = False
    for s in cfg.setdefault("sources", []):
        if s["id"] == "telegram":
            s["chats"] = chats
            s["enabled"] = bool(enable and chats)
            found = True
    if not found:
        cfg["sources"].append({"id": "telegram", "enabled": bool(enable and chats),
                               "label": "Telegram", "chats": chats, "per_chat": 40})
    engine.save_config(cfg)
