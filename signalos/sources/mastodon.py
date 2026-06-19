"""Mastodon — публичные ленты по хэштегам (без ключа). Ловим #buildinpublic, #startup и т.п., фильтруем по ключам."""
from . import get_json, strip_html, detect_lang, iso_ts


def search(keywords, cfg):
    inst = cfg.get("instance", "mastodon.social")
    tags = cfg.get("tags", ["buildinpublic", "startup", "indiehackers", "saas", "smallbusiness", "marketing"])
    out, seen = [], set()
    for tag in tags[: cfg.get("max_tags", 6)]:
        url = f"https://{inst}/api/v1/timelines/tag/{tag}?limit=20"
        try:
            data = get_json(url)
        except Exception:
            continue
        for s in (data if isinstance(data, list) else []):
            sid = s.get("id")
            if not sid or sid in seen:
                continue
            seen.add(sid)
            text = strip_html(s.get("content", ""))[:600]
            if len(text) < 20:
                continue
            acct = s.get("account") or {}
            out.append({
                "source": "mastodon", "source_label": "Mastodon",
                "external_id": f"masto:{sid}", "author": acct.get("acct", "?"),
                "text": text, "url": s.get("url", ""),
                "ts": iso_ts(s.get("created_at")), "lang": detect_lang(text),
            })
    return out
