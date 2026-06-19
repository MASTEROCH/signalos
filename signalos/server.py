"""
server.py — отдаёт дашборд + API. Чистый stdlib, без зависимостей.
Запуск:  python3 -m signalos.server   →  http://localhost:8000
Авто-сканирует источники при старте и по кнопке «Сканировать» в дашборде.
"""
import os, json, time, threading, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

from . import db, engine, setup, settings

PORT = int(os.environ.get("SIGNALOS_PORT", "8000"))
INTERVAL = int(os.environ.get("SIGNALOS_SCAN_INTERVAL", "900"))   # авто-скан каждые 15 мин
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_scanning = {"busy": False, "last": None}


def ago(ts):
    d = max(0, int(time.time() - (ts or 0)))
    if d < 3600: return f"{d//60} мин"
    if d < 86400: return f"{d//3600} ч"
    return f"{d//86400} дн"


def run_scan():
    if _scanning["busy"]:
        return {"busy": True}
    _scanning["busy"] = True
    try:
        s = engine.scan(); _scanning["last"] = s; return s
    finally:
        _scanning["busy"] = False


def is_configured():
    cfg = engine.load_config()
    return bool(cfg.get("configured")) and bool(cfg.get("projects"))


def do_setup(data):
    """Опиши продукт + подтверди фразы → авто-конфиг радара → первый скан. Сердце онбординга."""
    cfg = engine.load_config()
    if "sources" not in cfg:
        cfg["sources"] = [dict(s) for s in engine.DEFAULT_SOURCES]
    existing = [p["id"] for p in cfg.get("projects", [])]
    proj = setup.build_project(
        data.get("description", ""), data.get("link", "").strip(),
        data.get("phrases", []), name=data.get("name"), tone=data.get("tone"),
        subreddits=data.get("subreddits"), index=len(existing), existing_ids=existing)
    alerts = data.get("alerts", [])
    cfg.setdefault("projects", []).append(proj)
    cfg["configured"] = True
    # авто-расширяем источники под новый проект:
    for s in cfg["sources"]:
        if s["id"] == "reddit":
            s.setdefault("subreddits", [])
            for sub in proj.get("subreddits", []):
                if sub not in s["subreddits"]:
                    s["subreddits"].append(sub)
        if s["id"] == "rss":
            s.setdefault("feeds", [])
            # Reddit-поиск через RSS ловит и русские фразы (JSON-поиск часто заблокирован)
            for kw in proj["keywords"][:6]:
                q = urllib.parse.quote(kw)
                url = f"https://www.reddit.com/search.rss?q={q}&sort=new"
                if all(f.get("url") != url for f in s["feeds"] if isinstance(f, dict)):
                    s["feeds"].append({"label": f"web: {kw}", "url": url})
    engine.save_config(cfg)
    threading.Thread(target=run_scan, daemon=True).start()
    return {"ok": True, "project": {"id": proj["id"], "name": proj["name"], "color": proj["color"],
            "keywords": proj["keywords"], "tone": proj["tone"], "audience": proj.get("audience", ""),
            "subreddits": proj.get("subreddits", []), "alerts": alerts}}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/" or p == "/index.html":
            f = os.path.join(ROOT, "dashboard", "index.html")
            return self._send(200, open(f, "rb").read(), "text/html; charset=utf-8")
        if p == "/api/projects":
            cfg = engine.load_config()
            return self._send(200, [{"id": x["id"], "name": x["name"], "color": x.get("color", "#46f3c4"),
                                     "link": x["link"]} for x in cfg["projects"]])
        if p == "/api/sources":
            cfg = engine.load_config()
            out = []
            for s in cfg.get("sources", []):
                out.append({"id": s["id"], "enabled": s.get("enabled", False),
                            "label": s.get("label", s["id"]), "needs": s.get("needs", "")})
            return self._send(200, {"sources": out, "claude": bool(os.environ.get("ANTHROPIC_API_KEY")),
                                    "scanning": _scanning["busy"], "last": _scanning["last"]})
        if p == "/api/status":
            return self._send(200, {"configured": is_configured(),
                                    "claude": bool(os.environ.get("ANTHROPIC_API_KEY")),
                                    "scanning": _scanning["busy"], "last": _scanning["last"]})
        if p == "/api/settings":
            return self._send(200, settings.status())
        if p == "/api/telegram/check":
            return self._send(200, settings.check_telegram())
        if p == "/api/stats":
            return self._send(200, db.stats())
        if p == "/api/queue":
            project = "all"
            if "?" in self.path:
                from urllib.parse import parse_qs
                project = parse_qs(self.path.split("?")[1]).get("project", ["all"])[0]
            rows = db.queue(project)
            for r in rows:
                r["ago"] = ago(r["ts"]); r["chat"] = r["source_label"]
            return self._send(200, rows)
        return self._send(404, {"error": "not found"})

    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception:
            return {}

    def do_POST(self):
        p = self.path.split("?")[0]
        if p == "/api/suggest":
            b = self._body()
            desc = (b.get("description") or "").strip()
            if len(desc) < 8:
                return self._send(400, {"error": "опиши продукт чуть подробнее"})
            return self._send(200, setup.suggest(desc))
        if p == "/api/setup":
            b = self._body()
            if len((b.get("description") or "").strip()) < 8:
                return self._send(400, {"error": "опиши продукт чуть подробнее"})
            return self._send(200, do_setup(b))
        if p == "/api/settings/claude":
            b = self._body(); key = (b.get("key") or "").strip()
            if len(key) < 12:
                return self._send(400, {"error": "вставь ключ целиком"})
            return self._send(200, settings.save_claude(key))
        if p == "/api/settings/telegram":
            b = self._body()
            return self._send(200, settings.save_telegram(
                b.get("api_id"), b.get("api_hash"), b.get("phone"), b.get("chats", [])))
        if p == "/api/telegram/send_code":
            from . import tg_session
            b = self._body()
            api_id = str(b.get("api_id", "")).strip(); api_hash = (b.get("api_hash") or "").strip()
            phone = (b.get("phone") or "").strip()
            if not api_id.isdigit() or len(api_hash) < 10 or len(phone) < 5:
                return self._send(400, {"error": "Проверь api_id (число), api_hash и телефон"})
            if not tg_session.available():
                return self._send(200, {"error": "Telethon не установлен. Запусти через ./run.sh (venv)"})
            settings.set_env({"TELEGRAM_API_ID": api_id, "TELEGRAM_API_HASH": api_hash, "TELEGRAM_PHONE": phone})
            try:
                return self._send(200, tg_session.send_code(api_id, api_hash, phone))
            except Exception as e:
                return self._send(200, {"error": str(e)})
        if p == "/api/telegram/sign_in":
            from . import tg_session
            b = self._body()
            try:
                if b.get("password"):
                    res = tg_session.sign_in_password(b["password"])
                else:
                    res = tg_session.sign_in_code(b.get("code", ""))
                if res.get("connected"):
                    settings._set_tg_chats(settings._tg_chats(), enable=True)
                return self._send(200, res)
            except Exception as e:
                return self._send(200, {"error": str(e)})
        if p == "/api/scan":
            return self._send(200, run_scan())
        parts = p.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "source" and parts[3] == "toggle":
            sid = parts[2]; b = self._body()
            cfg = engine.load_config()
            for s in cfg.get("sources", []):
                if s["id"] == sid:
                    s["enabled"] = bool(b.get("enabled"))
            engine.save_config(cfg)
            return self._send(200, {"ok": True})
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "signal":
            sid = int(parts[2]); action = parts[3]
            if action in ("approve", "skip"):
                db.set_status(sid, "approved" if action == "approve" else "skipped")
                return self._send(200, {"ok": True})
        return self._send(404, {"error": "not found"})


def auto_scan_loop():
    """Радар сам ищет клиентов каждые INTERVAL секунд — кнопку жать не нужно."""
    while True:
        time.sleep(INTERVAL)
        if is_configured() and not _scanning["busy"]:
            run_scan()


def main():
    db.init()
    print(f"\n  🛰  SignalOS → http://localhost:{PORT}")
    print(f"     Claude: {'ON' if os.environ.get('ANTHROPIC_API_KEY') else 'OFF (бесплатный режим)'}")
    print(f"     Авто-поиск: каждые {INTERVAL//60} мин")
    if is_configured():
        threading.Thread(target=run_scan, daemon=True).start()
        print("     Радар настроен — первый поиск запущен…\n")
    else:
        print("     Радар ждёт настройки (открой дашборд → опиши продукт)…\n")
    threading.Thread(target=auto_scan_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
