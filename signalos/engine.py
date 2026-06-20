"""
engine.py — оркестратор сканирования, мультитенант.
Каждый пользователь — свой конфиг (проекты + источники + ключ) в БД, свои сигналы.
"""
import os, time
from . import db, classifier, sources, tg_bot

# Платформенный ИИ-ключ (для пользователей без своего ключа — за токены)
PLATFORM_KEY = os.environ.get("SIGNALOS_PLATFORM_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
COST_REPLY = 1       # токенов за ИИ-ответ на найденного клиента
COST_REGEN = 2       # за перегенерацию ответа
COST_SUGGEST = 5     # за умный подбор фраз в мастере
COST_IMPROVE = 5     # за ИИ-улучшение поисковой выдачи проекта

DEFAULT_SOURCES = [
    {"id": "hackernews", "enabled": True, "label": "HackerNews", "max_keywords": 6},
    {"id": "reddit", "enabled": True, "label": "Reddit", "max_keywords": 5,
     "subreddits": ["startups", "Entrepreneur", "smallbusiness"]},
    {"id": "bluesky", "enabled": True, "label": "Bluesky", "max_keywords": 6},
    {"id": "lemmy", "enabled": True, "label": "Lemmy", "max_keywords": 5, "instance": "lemmy.world"},
    {"id": "github", "enabled": True, "label": "GitHub", "max_keywords": 5},
    {"id": "stackexchange", "enabled": True, "label": "Stack Exchange", "max_keywords": 4, "site": "stackoverflow"},
    {"id": "mastodon", "enabled": True, "label": "Mastodon", "instance": "mastodon.social"},
    {"id": "lobsters", "enabled": False, "label": "Lobsters"},
    {"id": "rss", "enabled": True, "label": "Google Alerts / RSS", "feeds": []},
    # Telegram как ИСТОЧНИК скана убран: чтение чужих чатов через личную сессию = риск бана/ToS.
    # Telegram остаётся только как канал ДОСТАВКИ дайджеста (бот @BotFather) — без риска.
]


def default_config():
    return {"configured": False, "sources": [dict(s) for s in DEFAULT_SOURCES],
            "projects": [], "anthropic_key": "", "tg": {}}


def get_config(uid):
    cfg = db.get_config(uid) or default_config()
    have = {s["id"] for s in cfg.get("sources", [])}      # домержить новые каналы в старые конфиги
    for s in DEFAULT_SOURCES:
        if s["id"] not in have:
            cfg.setdefault("sources", []).append(dict(s))
    return cfg


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
            if "auto_improve" in f:
                p["auto_improve"] = bool(f["auto_improve"])
            if "resonance" in f and isinstance(f["resonance"], dict):
                r = f["resonance"]
                p["resonance"] = {
                    "ideal": str(r.get("ideal", "")).strip(),
                    "boost": [x.strip() for x in (r.get("boost") or []) if x and x.strip()][:30],
                    "penalty": [x.strip() for x in (r.get("penalty") or []) if x and x.strip()][:30],
                }
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
        boost = [b.lower() for b in (p.get("resonance") or {}).get("boost", [])]
        match = any(classifier._wordin(t, low) for t in toks) or any(b in low for b in boost)
        if match and not any(n.lower() in low for n in p.get("negative_keywords", [])):
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


def _ai_mode(uid, cfg):
    """Возвращает (key, platform): свой ключ → безлимит; иначе платформенный за токены; иначе free."""
    byo = cfg.get("anthropic_key", "")
    if byo:
        return byo, False
    u = db.get_user(uid)
    if PLATFORM_KEY and u and u["credits"] > 0:
        return PLATFORM_KEY, True
    return "", False


def scan_user(uid):
    cfg = get_config(uid)
    projects = cfg.get("projects", [])
    summary = {"fetched": 0, "signals": 0, "by_source": {}, "spent": 0}
    if not projects:
        return summary
    key, platform = _ai_mode(uid, cfg)
    u = db.get_user(uid)
    credits_left = u["credits"] if (u and platform) else 0
    kws = all_keywords(projects)
    db.init()
    for src in cfg.get("sources", []):
        if not src.get("enabled"):
            continue
        sid = src["id"]
        if sid == "telegram":          # личная TG-сессия больше не сканируется (де-риск)
            continue
        posts = sources.collect(sid, kws, _source_cfg(uid, src, cfg))
        summary["fetched"] += len(posts)
        found = 0
        for post in posts:
            if db.exists(uid, post["external_id"]):
                continue
            if not prefilter(post["text"], projects):
                continue
            if platform and credits_left < COST_REPLY:    # токены кончились → free-режим для остатка
                key, platform = "", False
            sig = classifier.process(post, projects, key)
            if sig and db.add(uid, post, sig):
                found += 1
                if platform and db.charge(uid, COST_REPLY):
                    credits_left -= COST_REPLY
                    summary["spent"] += COST_REPLY
        summary["by_source"][sid] = found
        summary["signals"] += found
    return summary


def improve_project(uid, pid):
    """ИИ улучшает ключевые фразы проекта под реальные сообщения клиентов (учёт одобрено/пропущено)."""
    cfg = get_config(uid)
    proj = next((p for p in cfg.get("projects", []) if p["id"] == pid), None)
    if not proj:
        return {"error": "нет проекта"}
    key, platform = _ai_mode(uid, cfg)
    if not key:
        return {"error": "Для ИИ-улучшения нужен Anthropic-ключ (свой в ⚙) или токены платформы.", "need_ai": True}
    if platform and not db.charge(uid, COST_IMPROVE):
        return {"error": "Недостаточно токенов", "need_tokens": True}
    sigs = db.recent_signals(uid, pid, 40)
    good = [s["text"][:220] for s in sigs if s.get("status") == "approved"][:8]
    bad = [s["text"][:220] for s in sigs if s.get("status") == "skipped"][:8]
    res = classifier.improve_keywords(proj, good, bad, key)
    if res and res.get("keywords"):
        proj["keywords"] = [k.strip() for k in res["keywords"] if k and k.strip()][:20]
        import time as _t
        proj["last_improve"] = _t.time()
        save_config(uid, cfg)
        return {"ok": True, "keywords": proj["keywords"], "note": res.get("note", ""),
                "charged": (COST_IMPROVE if platform else 0)}
    return {"error": "ИИ не вернул улучшения — попробуй ещё раз"}


# ---------- утренний дайджест (лицо продукта) ----------

def set_digest(uid, d):
    """Сохраняет настройки дайджест-бота. d: bot_token, bot_username, chat_id, chat_name,
    hour, tz_offset, min_strength, enabled."""
    cfg = get_config(uid)
    dg = cfg.setdefault("digest", {})
    for k in ("bot_token", "bot_username", "chat_id", "chat_name"):
        if d.get(k) is not None:
            dg[k] = str(d[k]).strip()
    if "enabled" in d:
        dg["enabled"] = bool(d["enabled"])
    if "hour" in d:
        try: dg["hour"] = max(0, min(23, int(d["hour"])))
        except Exception: pass
    if "tz_offset" in d:
        try: dg["tz_offset"] = max(-12, min(14, int(d["tz_offset"])))
        except Exception: pass
    if "min_strength" in d:
        try: dg["min_strength"] = max(1, min(5, int(d["min_strength"])))
        except Exception: pass
    save_config(uid, cfg)
    return dg


def _proj_name(cfg, pid):
    p = next((x for x in cfg.get("projects", []) if x["id"] == pid), None)
    return p["name"] if p else pid


def render_digest(cfg, rows):
    e = tg_bot.esc
    n = len(rows)
    head = (f"🛰 <b>{n} {_plural(n, 'искра','искры','искр')} готов{_plural(n,'а','ы','о')}</b> — живые люди, которым "
            f"ты прямо сейчас можешь помочь.\n")
    if not rows:
        return ("🛰 <b>Пока тихо.</b>\nРадар работает, но людей с настоящим запросом за ночь не нашлось — "
                "это нормально: лучше тишина, чем спам по случайным упоминаниям. Загляну снова завтра утром.")
    blocks = [head]
    for s in rows:
        stars = "🔥" if s.get("temp") == "hot" else "✨"
        proj = e(_proj_name(cfg, s.get("project", "")))
        excerpt = e((s.get("text") or "").strip().replace("\n", " "))[:200]
        why = e((s.get("why") or "").strip())[:160]
        b = [f"\n{stars} <b>{proj}</b> · резонанс {s.get('strength',0)}/5 · {e(s.get('source_label',''))}",
             f"«{excerpt}»"]
        if why:
            b.append(f"<i>{why}</i>")
        if s.get("draft"):
            b.append("💬 готовый ответ (тапни — скопируется):")
            b.append(f"<code>{e(s['draft'])}</code>")
        if s.get("url"):
            b.append(f"🔗 <a href=\"{e(s['url'])}\">открыть оригинал и ответить</a>")
        blocks.append("\n".join(b))
    blocks.append("\n— SignalOS · отвечай как человек, помоги первым, ссылку роняй один раз.")
    return "\n".join(blocks)


def _plural(n, one, few, many):
    n = abs(n) % 100
    if 11 <= n <= 14: return many
    d = n % 10
    if d == 1: return one
    if 2 <= d <= 4: return few
    return many


def send_digest(uid, force=False):
    cfg = get_config(uid)
    dg = cfg.get("digest") or {}
    token, chat = dg.get("bot_token"), dg.get("chat_id")
    if not (token and chat):
        return {"error": "Дайджест-бот не настроен: впиши токен и chat_id", "need_setup": True}
    since = 0 if force else (dg.get("last_sent") or 0)
    min_s = int(dg.get("min_strength", 4))
    rows = db.digest_signals(uid, since, min_s, 6)
    if not rows and not force:
        dg["last_sent"] = time.time()       # двигаем курсор, тишину при автозапуске не шлём
        cfg["digest"] = dg; save_config(uid, cfg)
        return {"ok": True, "count": 0}
    text = render_digest(cfg, rows)
    ok = tg_bot.send(token, str(chat), text)
    if ok:
        dg["last_sent"] = time.time()
        cfg["digest"] = dg
        save_config(uid, cfg)
    return {"ok": ok, "count": len(rows),
            "error": None if ok else "Telegram не принял сообщение — проверь токен и что ты нажал Start у бота"}


def regenerate(uid, sid):
    sig = db.get_signal(uid, sid)
    if not sig:
        return {"error": "нет такого сигнала"}
    cfg = get_config(uid)
    proj = next((p for p in cfg.get("projects", []) if p["id"] == sig["project"]), None)
    if not proj:
        return {"error": "нет проекта"}
    key, platform = _ai_mode(uid, cfg)
    if platform and not db.charge(uid, COST_REGEN):
        return {"error": "Недостаточно токенов", "need_tokens": True}
    post = {"text": sig["text"], "lang": sig["lang"], "source_label": sig["source_label"]}
    draft = classifier.make_draft(post, proj, key, sig.get("why", ""), variant=True)
    db.update_draft(uid, sid, draft)
    return {"ok": True, "draft": draft, "charged": (COST_REGEN if platform else 0)}
