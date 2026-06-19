"""
tg_session.py — вход в Telegram из интерфейса, мультитенант (сессия на пользователя).
Один фоновый event loop держит клиентов между запросами; состояние ключуется по имени сессии.
send_code → (код в Telegram) → sign_in_code → [2FA] sign_in_password → готово.
"""
import os, asyncio, threading

_loop = None
_state = {}   # session_name -> {client, phone, hash}


def available():
    try:
        import telethon  # noqa
        return True
    except ImportError:
        return False


def _ensure_loop():
    global _loop
    if _loop and _loop.is_running():
        return
    _loop = asyncio.new_event_loop()
    threading.Thread(target=_loop.run_forever, daemon=True).start()


def _run(coro, timeout=90):
    _ensure_loop()
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout)


def send_code(api_id, api_hash, phone, session):
    from telethon import TelegramClient
    os.makedirs(os.path.dirname(session) or ".", exist_ok=True)

    async def _do():
        st = _state.get(session)
        if st and st.get("client"):
            try: await st["client"].disconnect()
            except Exception: pass
        client = TelegramClient(session, int(api_id), api_hash)
        await client.connect()
        if await client.is_user_authorized():
            me = await client.get_me(); await client.disconnect()
            return {"connected": True, "name": me.first_name}
        sent = await client.send_code_request(phone)
        _state[session] = {"client": client, "phone": phone, "hash": sent.phone_code_hash}
        return {"sent": True}

    return _run(_do())


def sign_in_code(code, session):
    from telethon.errors import SessionPasswordNeededError

    async def _do():
        st = _state.get(session)
        if not st:
            return {"error": "Сначала запроси код"}
        try:
            await st["client"].sign_in(st["phone"], str(code).strip(), phone_code_hash=st["hash"])
        except SessionPasswordNeededError:
            return {"need_password": True}
        return await _finish(session)

    return _run(_do())


def sign_in_password(password, session):
    async def _do():
        st = _state.get(session)
        if not st:
            return {"error": "Сначала запроси код"}
        await st["client"].sign_in(password=password)
        return await _finish(session)

    return _run(_do())


async def _finish(session):
    st = _state.get(session)
    me = await st["client"].get_me()
    await st["client"].disconnect()
    _state.pop(session, None)
    return {"connected": True, "name": me.first_name}


def session_exists(session):
    return os.path.exists(session + ".session")
