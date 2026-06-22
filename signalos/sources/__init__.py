"""
Источники сигналов — плагины. Каждый возвращает список нормализованных постов:
  {source, source_label, external_id, author, text, url, ts, lang}

Бесплатные и без ключей: hackernews, reddit, rss (вкл. Google Alerts).
Опциональные (нужны ключи/либы): telegram.
"""
import json, gzip, urllib.request, urllib.parse, re

UA = "LeadOS/0.3 (lead radar; +https://github.com/roch)"


def http_get(url, timeout=12, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return data.decode("utf-8", "replace")


def strip_html(s):
    import html as _html
    return _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or ""))).strip()


def iso_ts(s):
    import calendar, time
    if not s:
        return int(time.time())
    s = str(s).split("+")[0].rstrip("Z")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return calendar.timegm(time.strptime(s, fmt))
        except Exception:
            pass
    return int(time.time())


def get_json(url, timeout=12, headers=None):
    return json.loads(http_get(url, timeout, headers))


def detect_lang(text):
    return "ru" if re.search(r"[а-яёА-ЯЁ]", text or "") else "en"


def collect(source_id, keywords, cfg):
    """Диспетчер: вызывает нужный источник. Возвращает [] при любой ошибке (не роняем радар)."""
    try:
        if source_id == "hackernews":
            from . import hackernews; return hackernews.search(keywords, cfg)
        if source_id == "reddit":
            from . import reddit; return reddit.search(keywords, cfg)
        if source_id == "bluesky":
            from . import bluesky; return bluesky.search(keywords, cfg)
        if source_id == "lemmy":
            from . import lemmy; return lemmy.search(keywords, cfg)
        if source_id == "github":
            from . import github; return github.search(keywords, cfg)
        if source_id == "stackexchange":
            from . import stackexchange; return stackexchange.search(keywords, cfg)
        if source_id == "mastodon":
            from . import mastodon; return mastodon.search(keywords, cfg)
        if source_id == "lobsters":
            from . import lobsters; return lobsters.search(keywords, cfg)
        if source_id == "rss":
            from . import rss; return rss.fetch(cfg)
        if source_id == "telegram":
            from . import telegram; return telegram.fetch(keywords, cfg)
    except Exception as e:
        print(f"  ⚠ источник {source_id}: {e}")
    return []
