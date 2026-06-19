"""
classifier.py — решает: это сигнал? какой проект? сила 1-5? + черновик ответа.

Два режима:
  • БЕЗ КЛЮЧА (бесплатно) — скоринг по ключевикам и фразам-намерениям + шаблонный черновик.
    Работает сразу, ноль настройки, ноль затрат.
  • С КЛЮЧОМ Anthropic — Claude классифицирует тоньше и пишет живой черновик.
    Включается автоматически, если задан ANTHROPIC_API_KEY.
Claude вызывается напрямую через urllib (SDK ставить не нужно).
"""
import os, json, re, urllib.request

CLASSIFY_MODEL = os.environ.get("SIGNALOS_CLASSIFY_MODEL", "claude-haiku-4-5")
DRAFT_MODEL = os.environ.get("SIGNALOS_DRAFT_MODEL", "claude-sonnet-4-6")


def current_key():
    """Читаем ключ динамически — чтобы включение из настроек работало без рестарта."""
    return os.environ.get("ANTHROPIC_API_KEY", "")

INTENT = {  # фразы-маркеры намерения → язык-независимый сигнал «человек ищет решение»
    "ru": ["посоветуйте", "подскажите", "кто знает", "ищу", "нужен", "нужна", "помогите",
           "как мне", "не понимаю", "теряю", "не успеваю", "посоветовать", "порекомендуйте",
           "что выбрать", "стоит ли", "замучился", "устал", "проблема с"],
    "en": ["looking for", "any recommendation", "recommend", "does anyone", "how do i",
           "need a", "need help", "struggling", "any tool", "suggestions", "alternative to",
           "how can i", "advice on", "is there a", "best way to"],
}


# слова, которые НЕ берём как ключ-токены (грамматика + общие intent-слова — они и так в INTENT)
KW_STOP = set("""для и в во на с со по о об у к от за из что как мне нам нас это эта эти же бы ли так
вот про над под при без они оно мой моя мои наш ваш ваша или есть быть ищу нужен нужна нужно нужны
хочу подскажите посоветуйте кто знает помогите where how what need looking for recommend any the and
a an to of in on is are my our your want anyone someone please""".split())


def keyword_tokens(keywords):
    """Бьём ключ-фразы на значимые слова-токены: 'ищу telegram mini app' → {telegram, mini, app}."""
    toks = set()
    for k in keywords:
        for w in re.findall(r"[a-zа-яё0-9]+", k.lower()):
            if len(w) >= 3 and w not in KW_STOP:
                toks.add(w)
    return toks


def _wordin(token, low):
    """Совпадение по границе слова (а не подстроке: 'app' не матчит 'happen')."""
    return re.search(r"(?<![a-zа-яё0-9])" + re.escape(token) + r"(?![a-zа-яё0-9])", low) is not None


# ---------- ПУБЛИЧНЫЙ API ----------
def process(post, projects):
    """Возвращает запись сигнала или None (шум)."""
    return _claude(post, projects) if current_key() else _free(post, projects)


# ---------- БЕСПЛАТНЫЙ РЕЖИМ ----------
def _free(post, projects):
    low = post["text"].lower()
    best, best_score, best_hits = None, 0, []
    intent_hits = sum(1 for ph in INTENT.get(post["lang"], []) if ph in low)
    q = 1 if "?" in post["text"] else 0
    for p in projects:
        neg = [n.lower() for n in p.get("negative_keywords", [])]
        if any(n in low for n in neg):
            continue
        toks = keyword_tokens(p.get("keywords", []))
        hit_toks = [t for t in toks if _wordin(t, low)]
        full_hits = [k.lower() for k in p.get("keywords", []) if k.lower() in low]   # бонус за фразу целиком
        # одиночный общий токен — слишком шумно для безключевого режима: нужна фраза целиком или ≥2 токена
        if not (full_hits or len(hit_toks) >= 2):
            continue
        score = len(hit_toks) + len(full_hits) * 2 + intent_hits * 2 + q
        if score > best_score:
            best, best_score, best_hits = p, score, (full_hits or hit_toks)
    if not best or best_score < 3:
        return None
    strength = max(1, min(5, best_score))
    if strength < best.get("min_strength", 3):
        return None
    temp = "hot" if best_score >= 6 else "warm" if best_score >= 4 else "cold"
    return {
        "project": best["id"], "temp": temp, "strength": strength,
        "conf": min(95, 45 + best_score * 7),
        "why": f"Совпадение по ключам: {', '.join(best_hits[:3])} + маркеры намерения.",
        "hl": best_hits[:3],
        "draft": _template(post, best, best_hits),
    }


def _template(post, project, hits=None):
    """Бесплатный черновик — живее и контекстнее: вариативные открытия, отсылка к словам человека,
    ветка по типу сигнала (вопрос / боль / скепсис). Это всё равно заготовка — настоящий контекст даёт Claude."""
    lang = post["lang"]
    text = post["text"]
    low = text.lower()
    link = project.get("link", "")
    idx = sum(ord(c) for c in text[:50]) % 3            # детерминированная вариативность (не всё одинаково)

    # тип сигнала
    is_q = "?" in text
    is_doubt = any(w in low for w in ["развод", "не верю", "боюсь", "сомнева", "scam", "really work",
                                      "actually work", "реально ли", "правда работает"])

    # «якорь» — отсылка к словам человека (только если язык совпадает, иначе не вставляем)
    topic = ""
    for h in (hits or []):
        h_ru = bool(re.search(r"[а-яё]", h))
        if (lang == "ru") == h_ru:
            topic = h; break

    if lang == "ru":
        if is_doubt:
            opener = ["Понимаю скепсис — сам так же сначала сомневался.",
                      "Резонно настороженно: на рынке правда много пустышек.",
                      "Честно — не всё работает, всё зависит от подхода."][idx]
        elif is_q:
            opener = ["Хороший вопрос — отвечу без воды.",
                      "Сталкивался ровно с этим, поделюсь чем закрыл.",
                      "Тут есть пара реально рабочих вариантов."][idx]
        else:
            opener = ["Знаю эту боль не понаслышке.",
                      "Прям откликается — был в такой же ситуации.",
                      "О, это частая история, и она решается."][idx]
        anchor = f" Особенно зацепило про «{topic}»." if topic else ""
        offer = ["Наткнулся недавно на штуку, которая ровно это закрывает — держи, глянь:",
                 "Есть вот такой проект под это, попробуй:",
                 "Мне в похожем кейсе зашло вот это:"][idx]
        return (f"{opener}{anchor} {offer} {link}".strip() if link
                else f"{opener}{anchor}".strip())

    if is_doubt:
        opener = ["I get the skepticism — I doubted it too at first.",
                  "Fair to be wary, there's a lot of fluff out there.",
                  "Honestly, not everything works — depends on the setup."][idx]
    elif is_q:
        opener = ["Good question — quick honest take.",
                  "Ran into exactly this, here's what worked for me.",
                  "There are a couple of genuinely solid options here."][idx]
    else:
        opener = ["I know this pain firsthand.",
                  "This really resonates — I've been there.",
                  "Comes up a lot, and it's fixable."][idx]
    anchor = f" The «{topic}» part especially." if topic else ""
    offer = ["Stumbled on a tool that nails exactly this — here, check it out:",
             "There's a project for this, give it a try:",
             "This worked for me in a similar spot:"][idx]
    return (f"{opener}{anchor} {offer} {link}".strip() if link
            else f"{opener}{anchor}".strip())


# ---------- РЕЖИМ CLAUDE ----------
def _claude(post, projects):
    brief = "\n".join(f"- id={p['id']} | {p['name']}: {p['one_liner']} | аудитория: {p['audience']}"
                      for p in projects)
    sys = ("Ты — radar лидов. Дано публичное сообщение. Реши: выражает ли автор боль/намерение, "
           "которое решает один из проектов. Большинство — шум (is_signal=false без колебаний). "
           f"Проекты:\n{brief}\n\n"
           'Верни СТРОГО JSON: {"is_signal":bool,"project_id":str|null,"strength":1-5,'
           '"confidence":0-100,"temp":"hot|warm|cold","reason":"одно предложение","highlight":["фразы"]}')
    data = _anthropic(CLASSIFY_MODEL, sys, f"Сообщение: {post['text']}", 400)
    j = _json(data)
    if not j or not j.get("is_signal"):
        return None
    proj = next((p for p in projects if p["id"] == j.get("project_id")), None)
    if not proj or j.get("strength", 0) < proj.get("min_strength", 3):
        return None
    lang = post["lang"]
    dsys = (
        f"Ты — обычный участник сообщества, который по-дружески делится полезной находкой "
        f"в ответ конкретному человеку. НЕ продавец и НЕ официальный представитель компании. "
        f"Вайб: «о, у меня была та же боль — наткнулся на штуку, держи, попробуй».\n"
        f"Продукт, которым делишься: {proj['one_liner']}\n"
        f"ССЫЛКА (вставляй ОБЯЗАТЕЛЬНО, естественно в тексте): {proj['link']}\n"
        f"Tone of voice: {proj['tone']}. Язык ответа строго: {'русский' if lang=='ru' else 'английский'}.\n"
        "КАК ПИСАТЬ (ответы НЕ должны быть однотипными):\n"
        "1. Реагируй на КОНКРЕТНЫЕ слова/детали/эмоцию его сообщения, не общими фразами.\n"
        "2. Никаких шаблонных зачинов ('Знакомая ситуация'/'Been there') и никакой рекламы/корпоративщины.\n"
        "3. Сначала эмпатия или польза по сути — потом ненавязчиво ссылка как личная рекомендация.\n"
        "4. Можно сказать что это твой проект, но НЕ обязательно — можно просто 'есть вот такой проект, держи'.\n"
        "5. Звучи как живой человек, который реально помогает, а не впаривает. 2–4 предложения. Ссылка обязательно.\n"
        "Верни ТОЛЬКО текст ответа, без кавычек и преамбул.")
    chat = post.get("source_label", "")
    draft = _anthropic(DRAFT_MODEL, dsys,
                       f"Где: {chat}\nЕго сообщение: «{post['text']}»\n"
                       f"Почему ему это зайдёт: {j.get('reason','')}\n\n"
                       f"Напиши дружеский ответ именно на ЭТО сообщение, с ненавязчивой ссылкой.", 320) or ""
    return {
        "project": proj["id"], "temp": j.get("temp", "warm"), "strength": j.get("strength", 3),
        "conf": j.get("confidence", 70), "why": j.get("reason", ""),
        "hl": j.get("highlight", []), "draft": draft.strip(),
    }


def _anthropic(model, system, user, max_tokens):
    body = json.dumps({"model": model, "max_tokens": max_tokens, "system": system,
                       "messages": [{"role": "user", "content": user}]}).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": current_key(), "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read())["content"][0]["text"]
    except Exception as e:
        print(f"  ⚠ claude: {e}")
        return None


def _json(text):
    if not text:
        return None
    try:
        s, e = text.find("{"), text.rfind("}")
        return json.loads(text[s:e + 1]) if s >= 0 else None
    except Exception:
        return None
