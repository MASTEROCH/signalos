"""
Одноразовый вход в Telegram, чтобы радар мог читать публичные чаты.

ПОЧЕМУ это нужно (и почему Telegram выключен по умолчанию):
У Telegram нет бесплатного публичного API «читать чат по ссылке» — в отличие от
HackerNews/Reddit/Bluesky/Lemmy. Чтобы читать, нужно один раз залогиниться своим
аккаунтом через официальное приложение. Это бесплатно и занимает 2 минуты:

  1) Зайди на https://my.telegram.org → API development tools → создай приложение.
     Получишь два числа/строки: api_id и api_hash.
  2) Впиши их в файл .env рядом с этим проектом:
        TELEGRAM_API_ID=12345678
        TELEGRAM_API_HASH=abcdef0123456789abcdef0123456789
  3) Установи библиотеку и войди один раз:
        pip install telethon
        python3 -m signalos.tg_login
     Введёшь номер телефона и код из Telegram — создастся локальный файл signalos.session.
  4) В config/config.json у источника telegram поставь "enabled": true и добавь чаты:
        "chats": ["startup_chat_ru", "batumi_chat"]

После этого радар сам читает эти чаты при каждом скане. Только чтение, без рассылки.
"""
import os, asyncio


async def main():
    api_id = int(os.environ.get("TELEGRAM_API_ID", "0"))
    api_hash = os.environ.get("TELEGRAM_API_HASH", "")
    if not (api_id and api_hash):
        print("✖ Не заданы TELEGRAM_API_ID / TELEGRAM_API_HASH.\n"
              "  Возьми их на https://my.telegram.org и впиши в .env (см. инструкцию в этом файле).")
        return
    try:
        from telethon import TelegramClient
    except ImportError:
        print("✖ Сначала установи библиотеку:  pip install telethon")
        return
    print("→ Вхожу в Telegram. Введи номер телефона и код из приложения…")
    async with TelegramClient("signalos", api_id, api_hash) as client:
        me = await client.get_me()
        print(f"✓ Готово! Вошёл как {me.first_name} (@{me.username}). Файл сессии создан.")
        print("  Теперь включи telegram в config/config.json и добавь чаты — радар начнёт их читать.")


if __name__ == "__main__":
    asyncio.run(main())
