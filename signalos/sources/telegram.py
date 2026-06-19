"""
Telegram — опциональный апгрейд для CIS/Батуми аудитории (твои реальные чаты).
Читает последние сообщения публичных чатов (ТОЛЬКО чтение). Нужны:
  pip install telethon  +  TELEGRAM_API_ID / TELEGRAM_API_HASH (my.telegram.org)
Первый запуск спросит телефон+код, создаст локальную сессию signalos.session.
Если не настроено — источник просто молчит, остальной радар работает.
"""
import os, asyncio, time
from . import detect_lang


def fetch(keywords, cfg):
    api_id = int(cfg.get("api_id") or os.environ.get("TELEGRAM_API_ID", "0") or 0)
    api_hash = cfg.get("api_hash") or os.environ.get("TELEGRAM_API_HASH", "")
    session = cfg.get("session", "signalos")
    chats = cfg.get("chats", [])
    if not (api_id and api_hash and chats):
        return []
    try:
        from telethon.sync import TelegramClient  # noqa
    except ImportError:
        print("  ⚠ telegram: установи  pip install telethon"); return []
    return asyncio.run(_pull(api_id, api_hash, session, chats, cfg.get("per_chat", 40)))


async def _pull(api_id, api_hash, session, chats, per_chat):
    from telethon import TelegramClient
    out = []
    async with TelegramClient(session, api_id, api_hash) as client:
        for chat in chats:
            try:
                ent = await client.get_entity(chat)
                title = getattr(ent, "title", chat)
                async for m in client.iter_messages(ent, limit=per_chat):
                    text = m.message or ""
                    if len(text) < 15:
                        continue
                    out.append({
                        "source": "telegram", "source_label": f"TG · {title}",
                        "external_id": f"tg:{m.chat_id}:{m.id}",
                        "author": str(getattr(m, "sender_id", "?")),
                        "text": text[:600],
                        "url": f"https://t.me/c/{abs(m.chat_id)}/{m.id}",
                        "ts": int(m.date.timestamp()) if m.date else int(time.time()),
                        "lang": detect_lang(text),
                    })
            except Exception as e:
                print(f"  ⚠ telegram {chat}: {e}")
    return out
