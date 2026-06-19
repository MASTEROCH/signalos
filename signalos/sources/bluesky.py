"""Bluesky — публичный поиск постов, БЕЗ ключа и без логина. Живая соцсеть, ловит RU+EN."""
import urllib.parse, time, calendar
from . import get_json, detect_lang


def search(keywords, cfg):
    out, seen = [], set()
    for kw in keywords[: cfg.get("max_keywords", 6)]:
        q = urllib.parse.quote(kw)
        url = (f"https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"
               f"?q={q}&limit=25&sort=latest")
        try:
            data = get_json(url)
        except Exception:
            continue
        for p in data.get("posts", []):
            uri = p.get("uri", "")
            if not uri or uri in seen:
                continue
            seen.add(uri)
            rec = p.get("record") or {}
            text = (rec.get("text") or "").strip()
            if len(text) < 20:
                continue
            author = p.get("author") or {}
            handle = author.get("handle", "")
            rkey = uri.split("/")[-1]
            out.append({
                "source": "bluesky", "source_label": "Bluesky",
                "external_id": f"bsky:{uri}", "author": handle,
                "text": text[:600],
                "url": f"https://bsky.app/profile/{handle}/post/{rkey}" if handle else "",
                "ts": _ts(rec.get("createdAt")), "lang": detect_lang(text),
            })
    return out


def _ts(s):
    if not s:
        return int(time.time())
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return calendar.timegm(time.strptime(s.replace("+00:00", "Z").split("+")[0].rstrip("Z") + "Z", fmt))
        except Exception:
            pass
    return int(time.time())
