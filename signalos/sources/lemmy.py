"""Lemmy — федеративный Reddit-аналог. Публичный поиск постов без ключа. По умолчанию инстанс lemmy.world."""
import urllib.parse, time, calendar
from . import get_json, detect_lang


def search(keywords, cfg):
    inst = cfg.get("instance", "lemmy.world")
    out, seen = [], set()
    for kw in keywords[: cfg.get("max_keywords", 5)]:
        q = urllib.parse.quote(kw)
        url = f"https://{inst}/api/v3/search?q={q}&type_=Posts&sort=New&limit=20"
        try:
            data = get_json(url)
        except Exception:
            continue
        for item in data.get("posts", []):
            post = item.get("post") or {}
            pid = post.get("id")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            text = (post.get("name", "") + ". " + (post.get("body", "") or "")).strip()
            if len(text) < 20:
                continue
            creator = item.get("creator") or {}
            out.append({
                "source": "lemmy", "source_label": f"Lemmy",
                "external_id": f"lemmy:{pid}", "author": creator.get("name", "?"),
                "text": text[:600], "url": post.get("ap_id", ""),
                "ts": _ts(post.get("published")), "lang": detect_lang(text),
            })
    return out


def _ts(s):
    if not s:
        return int(time.time())
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return calendar.timegm(time.strptime(s.split("+")[0].rstrip("Z") + "Z", fmt))
        except Exception:
            pass
    return int(time.time())
