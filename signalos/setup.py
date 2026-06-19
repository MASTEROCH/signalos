"""
setup.py — авто-настройка радара БЕЗ маркетинговых знаний.

Мастер не спрашивает «ключевые слова» (фаундер не знает что это). Он спрашивает по-человечески:
  «Что напишет человек, которому нужен твой продукт?»
Claude (если есть ключ) ПРЕДЛАГАЕТ эти фразы — ты подтверждаешь/правишь.
Без ключа — вписываешь пару фраз сам (это просто: «как бы твой клиент описал свою проблему»).

suggest(description) → подсказки для мастера (имя, фразы, где искать, tone, Google Alerts)
build_project(...)    → собирает финальный проект из подтверждённых данных
"""
import re
from . import classifier

PALETTE = ["#46f3c4", "#ff8ac4", "#5b8cff", "#ffd24a", "#E1FE71", "#7C3AFF", "#ff7a59"]

STOP = set("""the and for you your are with that this have from will what when how which but
который которая чтобы потому если когда нужно нужен нужна можно есть быть для что как это
про над под при без или они моя мой мои наш ваша только очень также делать сделать клиент
этого эта эти весь все всё себя меня тебя него неё них product service tool app бот сайт
продукт сервис компания клиентов делаю делаем чтобы""".split())


# ---------- ПОДСКАЗКИ ДЛЯ МАСТЕРА ----------
def suggest(description):
    return _claude_suggest(description) if classifier.current_key() else _heuristic_suggest(description)


def _claude_suggest(description):
    sys = (
        "Ты — маркетолог. Дано описание продукта от основателя. Помоги настроить поиск клиентов "
        "в публичных обсуждениях. Верни СТРОГО JSON:\n{\n"
        '  "name": "короткое имя продукта, 1-3 слова",\n'
        '  "phrases": ["10-14 ФРАЗ, которые реальный человек пишет когда ИЩЕТ такое решение или '
        'жалуется на боль, которую продукт решает. Это слова КЛИЕНТА, не реклама. Обязательно дай '
        'И на русском И на английском вперемешку"],\n'
        '  "subreddits": ["3-5 сабреддитов без r/, где сидит аудитория"],\n'
        '  "tone": "одна фраза: как по-человечески отвечать этим людям",\n'
        '  "alerts": ["3 коротких фразы для бесплатного Google Alerts"]\n}'
    )
    j = classifier._json(classifier._anthropic(classifier.DRAFT_MODEL, sys,
                         f"Описание продукта: {description}", 900)) or {}
    if not j.get("phrases"):
        return _heuristic_suggest(description)
    return {"name": j.get("name", _short_name(description)),
            "phrases": j["phrases"][:14],
            "subreddits": j.get("subreddits", ["startups", "Entrepreneur", "smallbusiness"]),
            "tone": j.get("tone", "Дружелюбно, от первого лица, сначала помощь — потом продукт."),
            "alerts": j.get("alerts", []), "smart": True}


def _heuristic_suggest(description):
    is_ru = bool(re.search(r"[а-яё]", description))
    words = [w for w in re.findall(r"[a-zа-яё]{4,}", description.lower()) if w not in STOP]
    freq = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    top = sorted(freq, key=lambda w: (-freq[w], -len(w)))[:5]
    lead = top[0] if top else (description.split()[0] if description.split() else "product")
    intent = (["ищу", "посоветуйте кто", "подскажите", "нужен", "как мне"] if is_ru
              else ["looking for", "recommend", "how do i", "need a"])
    phrases = [f"{i} {lead}" for i in intent] + top
    return {"name": _short_name(description), "phrases": phrases[:10],
            "subreddits": ["startups", "Entrepreneur", "smallbusiness"],
            "tone": "Дружелюбно, от первого лица, сначала помощь — потом продукт.",
            "alerts": top[:3], "smart": False}


# ---------- СБОРКА ПРОЕКТА ----------
def build_project(description, link, phrases, name=None, tone=None, subreddits=None,
                  index=0, existing_ids=None):
    existing_ids = existing_ids or []
    phrases = [p.strip() for p in (phrases or []) if p and p.strip()]
    if not phrases:                                  # подстраховка
        phrases = suggest(description)["phrases"]
    name = (name or _short_name(description)).strip()[:24]
    base = re.sub(r"[^a-z0-9]+", "", _translit(name.lower()))[:10] or "proj"
    pid, n = base, 1
    while pid in existing_ids:
        n += 1; pid = f"{base}{n}"
    return {
        "id": pid, "name": name, "color": PALETTE[index % len(PALETTE)],
        "link": link or "", "one_liner": description.strip()[:180],
        "audience": "Люди, которые обсуждают эту тему публично",
        "keywords": phrases[:18],
        "negative_keywords": ["вакансия", "ищу работу", "hiring", "job", "резюме"],
        "tone": tone or "Дружелюбно, от первого лица, сначала помощь — потом продукт.",
        "subreddits": subreddits or ["startups", "Entrepreneur", "smallbusiness"],
        "min_strength": 3,
    }


def _short_name(desc):
    words = [w for w in re.findall(r"[A-Za-zА-Яа-яё]+", desc) if len(w) > 2]
    return " ".join(words[:2]) if words else "Мой продукт"


def _translit(s):
    m = {"а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"e","ж":"zh","з":"z","и":"i","й":"y",
         "к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f",
         "х":"h","ц":"c","ч":"ch","ш":"sh","щ":"sch","ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya"}
    return "".join(m.get(c, c) for c in s)
