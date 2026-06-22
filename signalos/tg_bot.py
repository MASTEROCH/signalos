"""
tg_bot.py — доставка утреннего дайджеста через Telegram Bot API (@BotFather).
Без личной сессии и без риска бана: обычный бот-токен + chat_id, HTTPS-запросы.
Это «лицо продукта»: утром в личку прилетает «🛰 N искр готовы» с готовыми ответами
(тап по блоку кода = скопировать) и ссылками на оригиналы.
"""
import json, urllib.request, urllib.parse

API = "https://api.telegram.org/bot{token}/{method}"
MAXLEN = 4000   # лимит Telegram 4096, оставляем запас


def _call(token, method, params=None, timeout=15):
    url = API.format(token=token, method=method)
    data = urllib.parse.urlencode(params or {}).encode()
    req = urllib.request.Request(url, data=data if params else None,
                                 headers={"User-Agent": "LeadOS"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"ok": False, "description": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "description": str(e)}


def verify(token):
    """Проверяет токен. Возвращает {ok, username} или {ok:False, error}."""
    if not token or ":" not in token:
        return {"ok": False, "error": "Токен выглядит неправильно (формат 12345:ABC…)"}
    r = _call(token, "getMe")
    if r.get("ok"):
        u = r["result"]
        return {"ok": True, "username": u.get("username", ""), "name": u.get("first_name", "")}
    return {"ok": False, "error": r.get("description", "не удалось проверить токен")}


def detect_chat(token):
    """Находит chat_id того, кто недавно написал боту /start. Возвращает {ok, chat_id, name}."""
    r = _call(token, "getUpdates", {"limit": 10, "offset": -10})
    if not r.get("ok"):
        return {"ok": False, "error": r.get("description", "ошибка getUpdates")}
    chat = None
    for upd in reversed(r.get("result", [])):
        msg = upd.get("message") or upd.get("edited_message") or {}
        c = msg.get("chat")
        if c:
            chat = c
            break
    if not chat:
        return {"ok": False, "error": "Не вижу сообщений. Открой бота в Telegram и нажми «Start» (или напиши /start), потом повтори."}
    name = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])) or chat.get("username", "")
    return {"ok": True, "chat_id": str(chat["id"]), "name": name}


def send(token, chat_id, text):
    """Шлёт сообщение (HTML, без превью ссылок). Возвращает True/False."""
    if len(text) > MAXLEN:
        text = text[:MAXLEN].rsplit("\n", 1)[0] + "\n…"
    r = _call(token, "sendMessage", {
        "chat_id": chat_id, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    })
    return bool(r.get("ok"))


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
