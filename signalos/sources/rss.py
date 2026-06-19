"""
Универсальный RSS/Atom вход — самый хитрый источник.
Сюда подключается GOOGLE ALERTS: заводишь бесплатный алерт на ключевую фразу
(вкл. русский), Google отдаёт RSS-ленту → радар её читает. Плюс любой Reddit-search RSS,
форумы, блоги. Ноль ключей, любой язык, любой сайт.
"""
import time, calendar, re
from xml.etree import ElementTree as ET
from . import http_get, detect_lang


def fetch(cfg):
    out = []
    for feed in cfg.get("feeds", []):
        url = feed if isinstance(feed, str) else feed.get("url")
        label = "RSS" if isinstance(feed, str) else feed.get("label", "RSS")
        try:
            xml = http_get(url, timeout=12)
            out += _parse(xml, label)
        except Exception as e:
            print(f"  ⚠ rss {url}: {e}")
    return out


def _parse(xml, label):
    items = []
    root = ET.fromstring(xml)
    # снимаем namespace, чтобы единообразно искать item/entry
    for el in root.iter():
        el.tag = re.sub(r"\{.*\}", "", el.tag)
    nodes = root.findall(".//item") or root.findall(".//entry")
    for n in nodes:
        title = _txt(n, "title")
        body = _txt(n, "description") or _txt(n, "summary") or _txt(n, "content")
        link = _txt(n, "link") or _link_attr(n)
        text = _clean(f"{title}. {body}")
        if len(text) < 20:
            continue
        items.append({
            "source": "rss", "source_label": label,
            "external_id": "rss:" + (link or title)[:120],
            "author": _txt(n, "author") or label,
            "text": text[:600], "url": link or "",
            "ts": _ts(n), "lang": detect_lang(text),
        })
    return items


def _txt(n, tag):
    e = n.find(tag)
    return (e.text or "").strip() if e is not None and e.text else ""


def _link_attr(n):
    e = n.find("link")
    return e.get("href", "") if e is not None else ""


def _clean(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def _ts(n):
    for tag in ("pubDate", "updated", "published"):
        v = _txt(n, tag)
        if v:
            for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
                try:
                    return calendar.timegm(time.strptime(v.replace("Z", "+0000"), fmt))
                except Exception:
                    pass
    return int(time.time())
