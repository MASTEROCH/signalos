"""HackerNews через Algolia Search API — без ключа, мгновенно. Гоним и истории, и комменты."""
import urllib.parse, time
from . import get_json, detect_lang, strip_html


def search(keywords, cfg):
    out, seen = [], set()
    for kw in keywords[: cfg.get("max_keywords", 6)]:
        q = urllib.parse.quote(kw)
        url = (f"https://hn.algolia.com/api/v1/search_by_date"
               f"?query={q}&tags=(story,comment)&hitsPerPage=20")
        data = get_json(url)
        for h in data.get("hits", []):
            oid = h.get("objectID")
            if not oid or oid in seen:
                continue
            seen.add(oid)
            text = h.get("comment_text") or h.get("story_text") or h.get("title") or ""
            text = strip_html(text)
            if len(text) < 20:
                continue
            out.append({
                "source": "hackernews", "source_label": "HackerNews",
                "external_id": f"hn:{oid}", "author": h.get("author", "?"),
                "text": text, "url": f"https://news.ycombinator.com/item?id={oid}",
                "ts": h.get("created_at_i", int(time.time())), "lang": detect_lang(text),
            })
    return out
