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


def get_project(uid, pid):
    return next((p for p in get_config(uid).get("projects", []) if p["id"] == pid), None)


def update_project(uid, pid, f):
    cfg = get_config(uid)
    for p in cfg.get("projects", []):
        if p["id"] == pid:
            for k in ("name", "link", "one_liner", "audience", "tone"):
                if k in f and f[k] is not None:
                    p[k] = str(f[k]).strip()
            if "keywords" in f:
                p["keywords"] = [x.strip() for x in f["keywords"] if x and x.strip()]
            if "negative_keywords" in f:
                p["negative_keywords"] = [x.strip() for x in f["negative_keywords"] if x and x.strip()]
            if "min_strength" in f:
                try: p["min_strength"] = max(1, min(5, int(f["min_strength"])))
                except Exception: pass
            save_config(uid, cfg)
            return p
    return None


def delete_project(uid, pid):
    cfg = get_config(uid)
    cfg["projects"] = [p for p in cfg.get("projects", []) if p["id"] != pid]
    if not cfg["projects"]:
        cfg["configured"] = False
    save_config(uid, cfg)
    db.delete_project_signals(uid, pid)
    return {"ok": True}


def set_automation(uid, auto):
    cfg = get_config(uid)
    a = cfg.setdefault("automation", {})
    if "auto_scan" in auto: a["auto_scan"] = bool(auto["auto_scan"])
    if "min_strength" in auto:
        try: a["min_strength"] = max(1, min(5, int(auto["min_strength"])))
        except Exception: pass
    if "interval_min" in auto:
        try: a["interval_min"] = max(5, min(1440, int(auto["interval_min"])))
        except Exception: pass
    save_config(uid, cfg)
    return cfg.get("automation", {})


def set_source_config(uid, sid, conf):
    cfg = get_config(uid)
    for s in cfg.get("sources", []):
        if s["id"] == sid:
            for k, v in (conf or {}).items():
                if k in ("subreddits", "feeds", "chats"):
                    continue
                s[k] = v
    save_config(uid, cfg)
    return {"ok": True}


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
