"""
server.py — SaaS-сервер SignalOS (stdlib). Авторизация по cookie-сессии, данные по user_id.
Запуск:  ./run.sh   →  http://localhost:8000
"""
import os, json, time, threading, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

from . import db, engine, setup, settings, auth

PORT = int(os.environ.get("PORT") or os.environ.get("SIGNALOS_PORT", "8000"))   # хостинги задают PORT
INTERVAL = int(os.environ.get("SIGNALOS_SCAN_INTERVAL", "900"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_scanning = set()   # uids, по которым сейчас идёт скан

PLANS = {
    "free":   {"name": "Free",   "price": 0,   "products": 1,  "auto": False, "channels": "10 публичных каналов, ручной поиск", "interval": 1800},
    "pro":    {"name": "Pro",    "price": 29,  "products": 5,  "auto": True,  "channels": "Всё из Free + автопоиск 24/7 + Telegram + уведомления", "interval": 300},
    "agency": {"name": "Agency", "price": 99,  "products": 50, "auto": True,  "channels": "Всё из Pro + воркспейсы + команда + приоритет", "interval": 120},
}
# Пакеты токенов (оплата пока заглушка)
PACKS = {
    "s": {"tokens": 500,   "price": 5,  "label": "Старт"},
    "m": {"tokens": 2500,  "price": 20, "label": "Рост", "bonus": "+25%"},
    "l": {"tokens": 12000, "price": 80, "label": "Студия", "bonus": "+50%"},
}
COSTS = {"reply": engine.COST_REPLY, "regenerate": engine.COST_REGEN, "suggest": engine.COST_SUGGEST}


def scan(uid):
    if uid in _scanning:
        return {"busy": True}
    _scanning.add(uid)
    try:
        return engine.scan_user(uid)
    finally:
        _scanning.discard(uid)


def is_configured(uid):
    cfg = engine.get_config(uid)
    return bool(cfg.get("configured")) and bool(cfg.get("projects"))


def do_setup(uid, data):
    cfg = engine.get_config(uid)
    existing = [p["id"] for p in cfg.get("projects", [])]
    proj = setup.build_project(
        data.get("description", ""), data.get("link", "").strip(), data.get("phrases", []),
        name=data.get("name"), tone=data.get("tone"), subreddits=data.get("subreddits"),
        index=len(existing), existing_ids=existing)
    cfg.setdefault("projects", []).append(proj)
    cfg["configured"] = True
    for s in cfg.get("sources", []):
        if s["id"] == "reddit":
            s.setdefault("subreddits", [])
            for sub in proj.get("subreddits", []):
                if sub not in s["subreddits"]:
                    s["subreddits"].append(sub)
        if s["id"] == "rss":
            s.setdefault("feeds", [])
            for kw in proj["keywords"][:6]:
                url = "https://www.reddit.com/search.rss?q=" + urllib.parse.quote(kw) + "&sort=new"
                if all(f.get("url") != url for f in s["feeds"] if isinstance(f, dict)):
                    s["feeds"].append({"label": f"web: {kw}", "url": url})
    engine.save_config(uid, cfg)
    threading.Thread(target=lambda: scan(uid), daemon=True).start()
    return {"ok": True, "project": {"id": proj["id"], "name": proj["name"], "color": proj["color"]}}


def projects_of(uid):
    return [{"id": p["id"], "name": p["name"], "color": p.get("color", "#46f3c4"), "link": p.get("link", ""),
             "kw": len(p.get("keywords", []))}
            for p in engine.get_config(uid).get("projects", [])]


def sources_of(uid):
    cfg = engine.get_config(uid)
    out = [{"id": s["id"], "enabled": s.get("enabled", False), "label": s.get("label", s["id"])}
           for s in cfg.get("sources", [])]
    return {"sources": out, "claude": bool(cfg.get("anthropic_key")), "scanning": uid in _scanning}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    # ---------- helpers ----------
    def _send(self, code, body, ctype="application/json", cookie=None):
        b = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            return json.loads(self.rfile.read(n).decode("utf-8") or "{}") if n else {}
        except Exception:
            return {}

    def _token(self):
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            if part.strip().startswith("sid="):
                return part.strip()[4:]
        return None

    def _user(self):
        return auth.current_user(self._token())

    def _need(self):
        u = self._user()
        if not u:
            self._send(401, {"error": "Требуется вход"})
        return u

    # ---------- GET ----------
    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            return self._send(200, open(os.path.join(ROOT, "dashboard", "index.html"), "rb").read(),
                              "text/html; charset=utf-8")
        if p == "/api/auth/me":
            u = self._user()
            return self._send(200, {"user": auth._safe_user(u)} if u else {"user": None})

        u = self._need()
        if not u:
            return
        uid = u["id"]
        if p == "/api/status":
            return self._send(200, {"configured": is_configured(uid),
                                    "claude": bool(engine.get_config(uid).get("anthropic_key")),
                                    "scanning": uid in _scanning})
        if p == "/api/projects":
            return self._send(200, projects_of(uid))
        if p == "/api/sources":
            return self._send(200, sources_of(uid))
        if p == "/api/stats":
            return self._send(200, db.stats(uid))
        if p == "/api/settings":
            return self._send(200, settings.status(uid))
        if p == "/api/billing":
            return self._send(200, {"plan": u["plan"], "credits": u["credits"], "plans": PLANS,
                                    "packs": PACKS, "costs": COSTS, "platform_ai": bool(engine.PLATFORM_KEY),
                                    "byo": bool(engine.get_config(uid).get("anthropic_key"))})
        if p == "/api/queue":
            proj = "all"
            if "?" in self.path:
                proj = urllib.parse.parse_qs(self.path.split("?")[1]).get("project", ["all"])[0]
            rows = db.queue(uid, proj)
            for r in rows:
                r["ago"] = _ago(r["ts"]); r["chat"] = r["source_label"]
            return self._send(200, rows)
        if p == "/api/automation":
            return self._send(200, engine.get_config(uid).get("automation",
                              {"auto_scan": True, "interval_min": PLANS[u["plan"]]["interval"] // 60, "min_strength": 3}))
        if p == "/api/export":
            import csv, io
            rows = db.export_rows(uid)
            buf = io.StringIO(); w = csv.writer(buf)
            w.writerow(["Канал", "Проект", "Температура", "Сила", "Достоверность%", "Сообщение", "Ссылка", "Готовый ответ", "Статус", "Дата"])
            for r in rows:
                w.writerow([r["source_label"], r["project"], r["temp"], r["strength"], r["conf"],
                            r["text"], r["url"], r["draft"], r["status"],
                            time.strftime("%Y-%m-%d %H:%M", time.localtime(r["created"] or 0))])
            data = ("﻿" + buf.getvalue()).encode("utf-8")   # BOM для Excel
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename=signalos_leads.csv")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers(); self.wfile.write(data); return
        parts = p.strip("/").split("/")
        if len(parts) == 3 and parts[1] == "project":     # GET полные данные проекта
            pr = engine.get_project(uid, parts[2])
            return self._send(200, pr) if pr else self._send(404, {"error": "нет такого проекта"})
        return self._send(404, {"error": "not found"})

    # ---------- POST ----------
    def do_POST(self):
        p = self.path.split("?")[0]
        # --- авторизация (без сессии) ---
        if p == "/api/auth/register" or p == "/api/auth/login":
            b = self._body()
            r = (auth.register if p.endswith("register") else auth.login)(b.get("email"), b.get("password"))
            if r.get("error"):
                return self._send(400, r)
            ck = f"sid={r['token']}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000"
            return self._send(200, {"user": r["user"]}, cookie=ck)
        if p == "/api/auth/logout":
            auth.logout(self._token())
            return self._send(200, {"ok": True}, cookie="sid=; Path=/; Max-Age=0")

        u = self._need()
        if not u:
            return
        uid = u["id"]

        if p == "/api/setup":
            b = self._body()
            if len((b.get("description") or "").strip()) < 8:
                return self._send(400, {"error": "опиши продукт чуть подробнее"})
            return self._send(200, do_setup(uid, b))
        if p == "/api/suggest":
            b = self._body(); desc = (b.get("description") or "").strip()
            if len(desc) < 8:
                return self._send(400, {"error": "опиши продукт чуть подробнее"})
            cfg = engine.get_config(uid); key, platform = engine._ai_mode(uid, cfg)
            if platform and not db.charge(uid, engine.COST_SUGGEST):
                key = ""    # не хватило токенов → эвристика бесплатно
            return self._send(200, setup.suggest(desc, key))
        if p == "/api/regenerate":
            sid = self._body().get("signal_id")
            try:
                return self._send(200, engine.regenerate(uid, int(sid)))
            except Exception:
                return self._send(400, {"error": "плохой запрос"})
        if p == "/api/tokens/buy":
            pack = self._body().get("pack")
            if pack not in PACKS:
                return self._send(400, {"error": "неизвестный пакет"})
            db.add_credits(uid, PACKS[pack]["tokens"])
            return self._send(200, {"ok": True, "credits": db.get_user(uid)["credits"],
                                    "added": PACKS[pack]["tokens"], "demo": True})
        if p == "/api/scan":
            return self._send(200, scan(uid))
        if p == "/api/settings/claude":
            b = self._body(); key = (b.get("key") or "").strip()
            if len(key) < 12:
                return self._send(400, {"error": "вставь ключ целиком"})
            return self._send(200, settings.save_claude(uid, key))
        if p == "/api/settings/telegram":
            b = self._body()
            return self._send(200, settings.save_telegram(uid, b.get("api_id"), b.get("api_hash"),
                                                           b.get("phone"), b.get("chats", [])))
        if p == "/api/telegram/send_code":
            return self._send(200, settings.send_code(uid))
        if p == "/api/telegram/sign_in":
            b = self._body()
            return self._send(200, settings.sign_in(uid, b.get("code"), b.get("password")))
        if p == "/api/digest/verify":
            return self._send(200, settings.verify_digest_bot(uid, self._body().get("bot_token")))
        if p == "/api/digest/detect":
            return self._send(200, settings.detect_digest_chat(uid))
        if p == "/api/digest/save":
            return self._send(200, settings.save_digest(uid, self._body()))
        if p == "/api/digest/test":
            return self._send(200, settings.test_digest(uid))
        if p == "/api/billing/upgrade":
            b = self._body(); plan = b.get("plan", "free")
            if plan in PLANS:
                db.set_plan(uid, plan)
                return self._send(200, {"ok": True, "plan": plan, "demo": True})
            return self._send(400, {"error": "неизвестный план"})

        if p == "/api/automation":
            return self._send(200, engine.set_automation(uid, self._body()))
        parts = p.strip("/").split("/")
        if len(parts) == 4 and parts[1] == "source" and parts[3] == "toggle":
            return self._send(200, settings.toggle_source(uid, parts[2], self._body().get("enabled")))
        if len(parts) == 4 and parts[1] == "source" and parts[3] == "config":
            return self._send(200, engine.set_source_config(uid, parts[2], self._body()))
        if len(parts) == 4 and parts[1] == "project" and parts[3] == "delete":
            return self._send(200, engine.delete_project(uid, parts[2]))
        if len(parts) == 4 and parts[1] == "project" and parts[3] == "improve":
            return self._send(200, engine.improve_project(uid, parts[2]))
        if len(parts) == 3 and parts[1] == "project":     # POST обновить проект
            pr = engine.update_project(uid, parts[2], self._body())
            return self._send(200, pr) if pr else self._send(404, {"error": "нет такого проекта"})
        if len(parts) == 4 and parts[1] == "signal":
            sid = int(parts[2])
            if parts[3] in ("approve", "skip"):
                db.set_status(uid, sid, "approved" if parts[3] == "approve" else "skipped")
                return self._send(200, {"ok": True})
        return self._send(404, {"error": "not found"})


def _ago(ts):
    d = max(0, int(time.time() - (ts or 0)))
    if d < 3600: return f"{d//60} мин"
    if d < 86400: return f"{d//3600} ч"
    return f"{d//86400} дн"


_last_scan = {}
_digest_fired = {}   # uid -> местный день (год, yday), когда уже стрельнули — защита от дубля


def _local_day(now, tz):
    lt = time.gmtime(now + tz * 3600)
    return (lt.tm_year, lt.tm_yday)


def _digest_due(uid, cfg, now):
    """Дайджест-бот настроен, включён, наступил его час по местному времени, и сегодня ещё не слали."""
    dg = cfg.get("digest") or {}
    if not (dg.get("enabled") and dg.get("bot_token") and dg.get("chat_id")):
        return False
    tz = int(dg.get("tz_offset", 4)); hour = int(dg.get("hour", 9))
    today = _local_day(now, tz)
    if _digest_fired.get(uid) == today:                 # уже стреляли сегодня (in-memory guard)
        return False
    last = dg.get("last_sent") or 0
    if last and _local_day(last, tz) == today:          # переживает рестарт сервера
        return False
    return time.gmtime(now + tz * 3600).tm_hour >= hour


def _digest_job(uid):
    """Свежий скан → собрать и доставить дайджест в Telegram."""
    try:
        scan(uid)
    except Exception:
        pass
    try:
        engine.send_digest(uid)
    except Exception:
        pass


def auto_scan_loop():
    """Тикает раз в минуту; шлёт утренний дайджест и сканирует по автопилоту."""
    while True:
        time.sleep(60)
        now = time.time()
        for uid in db.all_user_ids():
            if uid in _scanning or not is_configured(uid):
                continue
            cfg0 = engine.get_config(uid)
            if _digest_due(uid, cfg0, now):            # «лицо продукта» — не зависит от тарифа
                tz = int((cfg0.get("digest") or {}).get("tz_offset", 4))
                _digest_fired[uid] = _local_day(now, tz)   # метим до запуска — защита от дубля
                threading.Thread(target=lambda x=uid: _digest_job(x), daemon=True).start()
            u = db.get_user(uid)
            if not PLANS.get(u["plan"], PLANS["free"])["auto"]:   # автопоиск — только на подписке
                continue
            cfg = engine.get_config(uid); auto = cfg.get("automation", {})
            if auto.get("auto_scan", True) is False:
                continue
            # ИИ-авто-улучшение ключей раз в сутки (для проектов с включённым флагом)
            for proj in cfg.get("projects", []):
                if proj.get("auto_improve") and (now - proj.get("last_improve", 0) > 86400):
                    try: engine.improve_project(uid, proj["id"])
                    except Exception: pass
            iv = (auto.get("interval_min") or (PLANS.get(u["plan"], PLANS["free"])["interval"] // 60)) * 60
            if now - _last_scan.get(uid, 0) >= iv:
                _last_scan[uid] = now
                threading.Thread(target=lambda x=uid: scan(x), daemon=True).start()


def main():
    db.init()
    os.makedirs("sessions", exist_ok=True)
    print(f"\n  🛰  SignalOS SaaS → http://localhost:{PORT}")
    print(f"     Авто-поиск: каждые {INTERVAL//60} мин для всех пользователей\n")
    threading.Thread(target=auto_scan_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
