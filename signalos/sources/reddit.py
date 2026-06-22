"""
Reddit. Без ключа — публичный JSON (часто ограничен/блокируется по IP).
С ключом (client_id/secret из настроек) — официальный OAuth API (oauth.reddit.com):
стабильнее, больше лимиты → шаг к автопилоту. Падает мягко в публичный режим при ошибке.
"""
import urllib.parse, urllib.request, base64, json, time
from . import get_json, detect_lang

_TOKEN = {}   # client_id -> (token, expires_at)


def _app_token(cfg):
    cid, cs = cfg.get("client_id"), cfg.get("client_secret")
    if not (cid and cs):
        return None
    cached = _TOKEN.get(cid)
    if cached and cached[1] > time.time():
        return cached[0]
    try:
        auth = base64.b64encode(f"{cid}:{cs}".encode()).decode()
        req = urllib.request.Request(
            "https://www.reddit.com/api/v1/access_token",
            data=b"grant_type=client_credentials",
            headers={"Authorization": "Basic " + auth, "User-Agent": "LeadOS/0.3"})
        with urllib.request.urlopen(req, timeout=12) as r:
            d = json.loads(r.read())
        t = d.get("access_token")
        if t:
            _TOKEN[cid] = (t, time.time() + d.get("expires_in", 3600) - 60)
            return t
    except Exception as e:
        print(f"  ⚠ reddit oauth: {e}")
    return None


def search(keywords, cfg):
    token = _app_token(cfg)
    base = "https://oauth.reddit.com" if token else "https://www.reddit.com"
    sp = "search" if token else "search.json"
    headers = {"Authorization": "bearer " + token} if token else None
    subs = cfg.get("subreddits", []) or ["all"]
    out, seen = [], set()
    for kw in keywords[: cfg.get("max_keywords", 5)]:
        q = urllib.parse.quote(kw)
        for tgt in subs:
            sr = "" if tgt == "all" else f"r/{tgt}/"
            restrict = "" if tgt == "all" else "&restrict_sr=1"
            url = f"{base}/{sr}{sp}?q={q}{restrict}&sort=new&limit=15&t=month"
            try:
                data = get_json(url, headers=headers)
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
