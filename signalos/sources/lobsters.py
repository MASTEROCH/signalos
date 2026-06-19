"""Lobste.rs — свежие посты tech-сообщества (без ключа). Возвращаем новейшее, фильтрует префильтр по ключам."""
import time
from . import get_json, strip_html, detect_lang, iso_ts


def search(keywords, cfg):
    out, seen = [], set()
    try:
        data = get_json("https://lobste.rs/newest.json")
    except Exception:
        return out
    for s in (data if isinstance(data, list) else [])[: cfg.get("limit", 25)]:
        sid = s.get("short_id")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        text = strip_html(s.get("title", "") + ". " + (s.get("description", "") or ""))[:600]
        if len(text) < 20:
            continue
        out.append({
            "source": "lobsters", "source_label": "Lobsters",
            "external_id": f"lob:{sid}", "author": (s.get("submitter_user") or {}).get("username", "?") if isinstance(s.get("submitter_user"), dict) else str(s.get("submitter_user", "?")),
            "text": text, "url": s.get("comments_url") or s.get("url", ""),
            "ts": iso_ts(s.get("created_at")), "lang": detect_lang(text),
        })
    return out
