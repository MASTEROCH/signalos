"""Reddit через публичный JSON — без ключа (нужен только User-Agent). Поиск по сабреддитам + глобально."""
import urllib.parse, time
from . import get_json, detect_lang


def search(keywords, cfg):
    out, seen = [], set()
    subs = cfg.get("subreddits", [])          # напр. ["startups","Entrepreneur","SaaS"]
    targets = [f"r/{s}" for s in subs] or ["all"]
    for kw in keywords[: cfg.get("max_keywords", 5)]:
        q = urllib.parse.quote(kw)
        for tgt in targets:
            sr = "" if tgt == "all" else f"r/{tgt.split('/')[-1]}/"
            restrict = "" if tgt == "all" else "&restrict_sr=1"
            url = (f"https://www.reddit.com/{sr}search.json"
                   f"?q={q}{restrict}&sort=new&limit=15&t=month")
            try:
                data = get_json(url)
            except Exception:
                continue
            for c in data.get("data", {}).get("children", []):
                d = c.get("data", {})
                oid = d.get("id")
                if not oid or oid in seen:
                    continue
                seen.add(oid)
                text = (d.get("title", "") + ". " + (d.get("selftext", "") or "")).strip()
                if len(text) < 20:
                    continue
                out.append({
                    "source": "reddit", "source_label": f"r/{d.get('subreddit','reddit')}",
                    "external_id": f"rd:{oid}", "author": d.get("author", "?"),
                    "text": text[:600], "url": "https://reddit.com" + d.get("permalink", ""),
                    "ts": int(d.get("created_utc", time.time())), "lang": detect_lang(text),
                })
    return out
