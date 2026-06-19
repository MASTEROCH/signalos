"""
engine.py — оркестратор сканирования.
Для каждого включённого источника: собрать посты → префильтр по ключевикам (экономим Claude)
→ классификатор → дедуп → сохранить сигнал. Возвращает сводку.
"""
import json, os
from . import db, classifier, sources

CONFIG = os.environ.get("SIGNALOS_CONFIG", "config/config.json")

DEFAULT_SOURCES = [
    {"id": "hackernews", "enabled": True, "label": "HackerNews", "max_keywords": 6},
    {"id": "reddit", "enabled": True, "label": "Reddit", "max_keywords": 5,
     "subreddits": ["startups", "Entrepreneur", "smallbusiness"]},
    {"id": "bluesky", "enabled": True, "label": "Bluesky", "max_keywords": 6},
    {"id": "lemmy", "enabled": True, "label": "Lemmy", "max_keywords": 5, "instance": "lemmy.world"},
    {"id": "rss", "enabled": True, "label": "Google Alerts / RSS", "feeds": []},
    {"id": "telegram", "enabled": False, "label": "Telegram", "chats": [], "per_chat": 40,
     "needs": "Бесплатный вход: my.telegram.org → API_ID/HASH → python3 -m signalos.tg_login"},
]


def load_config():
    if os.path.exists(CONFIG):
        return json.load(open(CONFIG, encoding="utf-8"))
    # ещё не настроен — радар ждёт онбординга
    return {"configured": False, "sources": [dict(s) for s in DEFAULT_SOURCES], "projects": []}


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG) or ".", exist_ok=True)
    json.dump(cfg, open(CONFIG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return cfg


def all_keywords(projects):
    kws = []
    for p in projects:
        kws += p.get("keywords", [])
    seen, out = set(), []
    for k in kws:
        if k.lower() not in seen:
            seen.add(k.lower()); out.append(k)
    return out


def prefilter(text, projects):
    """Пропускаем пост к классификатору, если есть совпадение по значимым словам-токенам ключей."""
    low = text.lower()
    if len(low) < 20:
        return False
    for p in projects:
        toks = classifier.keyword_tokens(p.get("keywords", []))
        if any(classifier._wordin(t, low) for t in toks):
            if not any(n.lower() in low for n in p.get("negative_keywords", [])):
                return True
    return False


def scan():
    cfg = load_config()
    projects = cfg["projects"]
    kws = all_keywords(projects)
    db.init()
    summary = {"fetched": 0, "signals": 0, "by_source": {}}

    for src in cfg.get("sources", []):
        if not src.get("enabled"):
            continue
        sid = src["id"]
        posts = sources.collect(sid, kws, src)
        summary["fetched"] += len(posts)
        found = 0
        for post in posts:
            if db.exists(post["external_id"]):
                continue
            if not prefilter(post["text"], projects):
                continue
            sig = classifier.process(post, projects)
            if sig and db.add(post, sig):
                found += 1
        summary["by_source"][sid] = found
        summary["signals"] += found
        print(f"  ✓ {sid}: {len(posts)} постов → {found} новых сигналов")
    return summary


if __name__ == "__main__":
    print("SignalOS scan…"); print(scan())
