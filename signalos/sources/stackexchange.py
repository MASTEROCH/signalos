"""Stack Exchange — Q&A, где спрашивают «how do I / looking for». Без ключа (300/день), с ключом — 10k."""
import urllib.parse, time
from . import get_json, strip_html, detect_lang


def search(keywords, cfg):
    site = cfg.get("site", "stackoverflow")
    key = ("&key=" + cfg["key"]) if cfg.get("key") else ""
    out, seen = [], set()
    for kw in keywords[: cfg.get("max_keywords", 4)]:
        q = urllib.parse.quote(kw)
        url = (f"https://api.stackexchange.com/2.3/search/advanced?order=desc&sort=creation"
               f"&q={q}&site={site}&pagesize=12&filter=withbody{key}")
        try:
            data = get_json(url)
        except Exception:
            continue
        for it in data.get("items", []):
            qid = it.get("question_id")
            if not qid or qid in seen:
                continue
            seen.add(qid)
            text = strip_html(it.get("title", "") + ". " + (it.get("body", "") or ""))[:600]
            if len(text) < 20:
                continue
            out.append({
                "source": "stackexchange", "source_label": "Stack Exchange",
                "external_id": f"se:{site}:{qid}", "author": (it.get("owner") or {}).get("display_name", "?"),
                "text": text, "url": it.get("link", ""),
                "ts": int(it.get("creation_date", time.time())), "lang": detect_lang(text),
            })
    return out
