"""db.py — мультитенантное хранилище SaaS (SQLite). Всё изолировано по user_id."""
import os, json, sqlite3, time

DB = os.environ.get("SIGNALOS_DB", "signalos.db")


def _c():
    c = sqlite3.connect(DB, timeout=10); c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL"); return c


def init():
    with _c() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE, pass_hash TEXT, salt TEXT,
            plan TEXT DEFAULT 'free', credits INTEGER DEFAULT 300, created REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS sessions(
            token TEXT PRIMARY KEY, user_id INTEGER, created REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS configs(
            user_id INTEGER PRIMARY KEY, data TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS signals(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            external_id TEXT, source TEXT, source_label TEXT, project TEXT,
            author TEXT, text TEXT, url TEXT, temp TEXT, strength INTEGER, conf INTEGER,
            why TEXT, hl TEXT, draft TEXT, lang TEXT, status TEXT DEFAULT 'queue',
            ts REAL, created REAL,
            UNIQUE(user_id, external_id))""")


# ---------- users ----------
def create_user(email, pass_hash, salt):
    with _c() as c:
        cur = c.execute("INSERT INTO users(email,pass_hash,salt,created) VALUES(?,?,?,?)",
                        (email.lower().strip(), pass_hash, salt, time.time()))
        return cur.lastrowid


def get_user_by_email(email):
    with _c() as c:
        r = c.execute("SELECT * FROM users WHERE email=?", (email.lower().strip(),)).fetchone()
        return dict(r) if r else None


def get_user(uid):
    with _c() as c:
        r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        return dict(r) if r else None


def set_plan(uid, plan, credits=None):
    with _c() as c:
        if credits is None:
            c.execute("UPDATE users SET plan=? WHERE id=?", (plan, uid))
        else:
            c.execute("UPDATE users SET plan=?, credits=? WHERE id=?", (plan, credits, uid))


def add_credits(uid, delta):
    with _c() as c:
        c.execute("UPDATE users SET credits=MAX(0,credits+?) WHERE id=?", (delta, uid))


# ---------- sessions ----------
def create_session(uid, token):
    with _c() as c:
        c.execute("INSERT INTO sessions(token,user_id,created) VALUES(?,?,?)", (token, uid, time.time()))


def session_user(token):
    if not token:
        return None
    with _c() as c:
        r = c.execute("SELECT user_id FROM sessions WHERE token=?", (token,)).fetchone()
        return r["user_id"] if r else None


def delete_session(token):
    with _c() as c:
        c.execute("DELETE FROM sessions WHERE token=?", (token,))


# ---------- per-user config (projects + sources + keys) ----------
def get_config(uid):
    with _c() as c:
        r = c.execute("SELECT data FROM configs WHERE user_id=?", (uid,)).fetchone()
    return json.loads(r["data"]) if r else None


def save_config(uid, cfg):
    with _c() as c:
        c.execute("INSERT INTO configs(user_id,data) VALUES(?,?) "
                  "ON CONFLICT(user_id) DO UPDATE SET data=excluded.data",
                  (uid, json.dumps(cfg, ensure_ascii=False)))


# ---------- signals ----------
def exists(uid, external_id):
    with _c() as c:
        return c.execute("SELECT 1 FROM signals WHERE user_id=? AND external_id=?",
                         (uid, external_id)).fetchone() is not None


def add(uid, post, sig):
    try:
        with _c() as c:
            c.execute("""INSERT OR IGNORE INTO signals
                (user_id,external_id,source,source_label,project,author,text,url,temp,strength,conf,why,hl,draft,lang,status,ts,created)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'queue',?,?)""",
                (uid, post["external_id"], post["source"], post["source_label"], sig["project"],
                 post.get("author", ""), post["text"], post.get("url", ""), sig["temp"],
                 sig["strength"], sig["conf"], sig["why"],
                 json.dumps(sig.get("hl", []), ensure_ascii=False), sig["draft"],
                 post.get("lang", "en"), post.get("ts", time.time()), time.time()))
            return c.total_changes > 0
    except Exception:
        return False


def queue(uid, project=None):
    q = "SELECT * FROM signals WHERE user_id=? AND status='queue'"; a = [uid]
    if project and project != "all":
        q += " AND project=?"; a.append(project)
    q += " ORDER BY strength DESC, ts DESC LIMIT 200"
    with _c() as c:
        rows = c.execute(q, a).fetchall()
    out = []
    for r in rows:
        d = dict(r); d["hl"] = json.loads(d["hl"] or "[]"); out.append(d)
    return out


def set_status(uid, sid, status):
    with _c() as c:
        c.execute("UPDATE signals SET status=? WHERE id=? AND user_id=?", (status, sid, uid))


def stats(uid):
    with _c() as c:
        row = c.execute("""SELECT
            SUM(status='queue') q, SUM(status='approved') a, SUM(status='skipped') s,
            SUM(status='queue' AND temp='hot') hot, SUM(created > ?) today
            FROM signals WHERE user_id=?""", (time.time() - 86400, uid)).fetchone()
    return {"queue": row["q"] or 0, "approved": row["a"] or 0, "skipped": row["s"] or 0,
            "hot": row["hot"] or 0, "today": row["today"] or 0}


def delete_project_signals(uid, pid):
    with _c() as c:
        c.execute("DELETE FROM signals WHERE user_id=? AND project=?", (uid, pid))


def all_user_ids():
    with _c() as c:
        return [r["user_id"] for r in c.execute("SELECT user_id FROM configs").fetchall()]
