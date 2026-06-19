"""
engine.py — оркестратор сканирования, мультитенант.
Каждый пользователь — свой конфиг (проекты + источники + ключ) в БД, свои сигналы.
"""
from . import db, classifier, sources

DEFAULT_SOURCES = [
    {"id": "hackernews", "enabled": True, "label": "HackerNews", "max_keywords": 6},
    {"id": "reddit", "enabled": True, "label": "Reddit", "max_keywords": 5,
     "subreddits": ["startups", "Entrepreneur", "smallbusiness"]},
    {"id": "bluesky", "enabled": True, "label": "Bluesky", "max_keywords": 6},
    {"id": "lemmy", "enabled": True, "label": "Lemmy", "max_keywords": 5, "instance": "lemmy.world"},
    {"id": "rss", "enabled": True, "label": "Google Alerts / RSS", "feeds": []},
    {"id": "telegram", "enabled": False, "label": "Telegram", "chats": [], "per_chat": 40},
]


def default_config():
    return {"configured": False, "sources": [dict(s) for s in DEFAULT_SOURCES],
            "projects": [], "anthropic_key": "", "tg": {}}


def get_config(uid):
    return db.get_config(uid) or default_config()


def save_config(uid, cfg):
    db.save_config(uid, cfg)


def all_keywords(projects):
    seen, out = set(), []
    for p in projects:
        for k in p.get("keywords", []):
            if k.lower() not in seen:
                seen.add(k.lower()); out.append(k)
    return out


def prefilter(text, projects):
    low = text.lower()
    if len(low) < 20:
        return False
    for p in projects:
        toks = classifier.keyword_tokens(p.get("keywords", []))
        if any(classifier._wordin(t, low) for t in toks):
            if not any(n.lower() in low for n in p.get("negative_keywords", [])):
                return True
    return False


def _source_cfg(uid, src, cfg):
    """Готовит конфиг источника. Для telegram подставляет креды/сессию пользователя."""
    s = dict(src)
    if src["id"] == "telegram":
        tg = cfg.get("tg", {})
        s["api_id"] = tg.get("api_id"); s["api_hash"] = tg.get("api_hash")
        s["session"] = f"sessions/u{uid}"; s["chats"] = tg.get("chats", src.get("chats", []))
    return s


def scan_user(uid):
    cfg = get_config(uid)
    projects = cfg.get("projects", [])
    summary = {"fetched": 0, "signals": 0, "by_source": {}}
    if not projects:
        return summary
    key = cfg.get("anthropic_key", "")
    kws = all_keywords(projects)
    db.init()
    for src in cfg.get("sources", []):
        if not src.get("enabled"):
            continue
        sid = src["id"]
        posts = sources.collect(sid, kws, _source_cfg(uid, src, cfg))
        summary["fetched"] += len(posts)
        found = 0
        for post in posts:
            if db.exists(uid, post["external_id"]):
                continue
            if not prefilter(post["text"], projects):
                continue
            sig = classifier.process(post, projects, key)
            if sig and db.add(uid, post, sig):
                found += 1
        summary["by_source"][sid] = found
        summary["signals"] += found
    return summary
