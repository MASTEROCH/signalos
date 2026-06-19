"""
tg_session.py — вход в Telegram прямо из интерфейса, без терминала.

Telethon — асинхронный, а наш сервер — обычные потоки. Поэтому держим ОДИН выделенный
event loop в фоновом потоке, который владеет клиентом между запросами:
  send_code → (приходит код в Telegram) → sign_in_code → [если 2FA] sign_in_password → готово.
После успешного входа сессия сохраняется в signalos.session, и сканер читает чаты сам.
"""
import asyncio, threading

_loop = None
_state = {"client": None, "phone": None, "hash": None}


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


def send_code(api_id, api_hash, phone):
    from telethon import TelegramClient

    async def _do():
        if _state["client"]:
            try:
                await _state["client"].disconnect()
            except Exception:
                pass
            _state["client"] = None
        client = TelegramClient("signalos", int(api_id), api_hash)
        await client.connect()
        if await client.is_user_authorized():           # уже входили раньше
            me = await client.get_me()
            await client.disconnect()
            return {"connected": True, "name": me.first_name}
        sent = await client.send_code_request(phone)
        _state.update(client=client, phone=phone, hash=sent.phone_code_hash)
        return {"sent": True}

    return _run(_do())


def sign_in_code(code):
    from telethon.errors import SessionPasswordNeededError

    async def _do():
        client = _state["client"]
        if not client:
            return {"error": "Сначала запроси код"}
        try:
            await client.sign_in(_state["phone"], str(code).strip(), phone_code_hash=_state["hash"])
        except SessionPasswordNeededError:
            return {"need_password": True}
        return await _finish(client)

    return _run(_do())


def sign_in_password(password):
    async def _do():
        client = _state["client"]
        if not client:
            return {"error": "Сначала запроси код"}
        await client.sign_in(password=password)
        return await _finish(client)

    return _run(_do())


async def _finish(client):
    me = await client.get_me()
    await client.disconnect()      # освобождаем файл сессии для сканера
    _state["client"] = None
    return {"connected": True, "name": me.first_name}
