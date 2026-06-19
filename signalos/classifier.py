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


# ---------- ПУБЛИЧНЫЙ API ----------
def process(post, projects):
    """Возвращает запись сигнала или None (шум)."""
    return _claude(post, projects) if current_key() else _free(post, projects)


# ---------- БЕСПЛАТНЫЙ РЕЖИМ ----------
def _free(post, projects):
    text = post["text"].lower()
    best, best_score = None, 0
    for p in projects:
        kws = [k.lower() for k in p.get("keywords", [])]
        neg = [n.lower() for n in p.get("negative_keywords", [])]
        if any(n in text for n in neg):
            continue
        hits = [k for k in kws if k in text]
        if not hits:
            continue
        score = len(hits) * 2
        score += sum(1 for ph in INTENT.get(post["lang"], []) if ph in text) * 2
        score += 1 if "?" in post["text"] else 0
        if score > best_score:
            best, best_score, best_hits = p, score, hits
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
        offer = ["Если интересно — скину пример, без втюхивания.",
                 "Могу показать, как мы это закрыли.",
                 "Накину детали в личку, если зайдёт."][idx]
        return f"{opener}{anchor} {offer} {link}".strip()

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
    offer = ["Happy to share a concrete example, no pressure.",
             "Can show you how we solved it.",
             "I'll DM you the details if it's useful."][idx]
    return f"{opener}{anchor} {offer} {link}".strip()


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
        f"Ты — основатель проекта '{proj['name']}' и пишешь живой ответ конкретному человеку "
        f"в его ветке/чате. Tone of voice: {proj['tone']}. Продукт: {proj['one_liner']} "
        f"Ссылка (вставляй ТОЛЬКО если реально уместно): {proj['link']}. "
        f"Язык ответа строго: {'русский' if lang=='ru' else 'английский'}.\n"
        "КАК ПИСАТЬ (это важно — ответы НЕ должны быть однотипными):\n"
        "1. Реагируй на КОНКРЕТНЫЕ слова и детали из его сообщения, а не общими фразами. "
        "Зацепись за то, что он реально написал (его ситуацию, цифры, эмоцию).\n"
        "2. Никаких шаблонных зачинов вроде 'Знакомая ситуация' / 'Been there'. Начни по-разному, "
        "из сути именно этого сообщения.\n"
        "3. Сначала реальная польза или конкретное наблюдение — потом, мягко и опционально, продукт.\n"
        "4. Звучи как живой человек в этом сообществе: разговорно, без корпоративщины и рекламы.\n"
        "5. 2–4 предложения. Можно задать встречный вопрос или предложить что-то конкретное.\n"
        "Верни ТОЛЬКО текст ответа, без кавычек и преамбул.")
    chat = post.get("source_label", "")
    draft = _anthropic(DRAFT_MODEL, dsys,
                       f"Где: {chat}\nЕго сообщение: «{post['text']}»\n"
                       f"Почему он потенциальный клиент: {j.get('reason','')}\n\n"
                       f"Напиши ответ именно на ЭТО сообщение.", 320) or ""
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
