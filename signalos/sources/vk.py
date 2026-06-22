"""
vk.py — поиск публичных постов ВКонтакте по ключевым словам (официальный API).
Метод newsfeed.search: глобальный поиск свежих постов. Нужен user access-token (бесплатно).
Опционально latitude/longitude — гео-поиск (например, рядом с Батуми).
"""
import urllib.parse, time
from . import get_json, strip_html, detect_lang

API = "https://api.vk.com/method/newsfeed.search"
VER = "5.131"


def search(keywords, cfg):
    token = (cfg.get("token") or "").strip()
    if not token or not keywords:
        return []
    out, seen = [], set()
    for kw in keywords[: cfg.get("max_keywords", 5)]:
        params = {"q": kw, "count": cfg.get("count", 40), "access_token": token, "v": VER}
        if cfg.get("latitude") and cfg.get("longitude"):
            params["latitude"] = cfg["latitude"]
            params["longitude"] = cfg["longitude"]
        try:
            data = get_json(API + "?" + urllib.parse.urlencode(params))
        except Exception:
            continue
        if data.get("error"):                      # неверный/протухший токен и т.п.
            continue
        for it in (data.get("response") or {}).get("items", []):
            oid = it.get("owner_id", it.get("from_id"))
            pid = it.get("id")
            if oid is None or pid is None:
                continue
            ext = f"vk_{oid}_{pid}"
            if ext in seen:
                continue
            seen.add(ext)
            text = strip_html(it.get("text", ""))
            if len(text) < 15:
                continue
            out.append({
                "source": "vk", "source_label": "VK",
                "external_id": ext, "author": str(oid),
                "text": text, "url": f"https://vk.com/wall{oid}_{pid}",
                "ts": int(it.get("date", time.time())), "lang": detect_lang(text),
            })
    return out
