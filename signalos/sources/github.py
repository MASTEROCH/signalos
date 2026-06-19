"""GitHub — поиск issues/discussions, где люди ищут инструмент («looking for a tool…»). Без ключа (лимит 10/мин), с токеном — больше."""
import urllib.parse, time
from . import get_json, strip_html, detect_lang, iso_ts


def search(keywords, cfg):
    out, seen = [], set()
    hdr = {"Accept": "application/vnd.github+json"}
    if cfg.get("token"):
        hdr["Authorization"] = "Bearer " + cfg["token"]
    for kw in keywords[: cfg.get("max_keywords", 5)]:
        q = urllib.parse.quote(f'"{kw}" in:title,body state:open')
        url = f"https://api.github.com/search/issues?q={q}&sort=created&order=desc&per_page=12"
        try:
            data = get_json(url, headers=hdr)
        except Exception:
            continue
        for it in data.get("items", []):
            iid = it.get("id")
            if not iid or iid in seen:
                continue
            seen.add(iid)
            text = strip_html(it.get("title", "") + ". " + (it.get("body", "") or ""))[:600]
            if len(text) < 20:
                continue
            out.append({
                "source": "github", "source_label": "GitHub",
                "external_id": f"gh:{iid}", "author": (it.get("user") or {}).get("login", "?"),
                "text": text, "url": it.get("html_url", ""),
                "ts": iso_ts(it.get("created_at")), "lang": detect_lang(text),
            })
    return out
