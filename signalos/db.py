"""db.py — мультитенантное хранилище SaaS. Postgres (psycopg2) если есть DATABASE_URL, иначе SQLite."""
import os, json, sqlite3, time

# ---------- backend detection ----------
DATABASE_URL = os.environ.get("DATABASE_URL", "")
_USE_PG = bool(DATABASE_URL)

if _USE_PG:
    import psycopg2
    import psycopg2.extras

DB = os.environ.get("SIGNALOS_DB", "signalos.db")

# ---------- connection helpers ----------

def _pg():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return conn

def _c():
    c = sqlite3.connect(DB, timeout=10); c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL"); return c


def init():
    if _USE_PG:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS users(
            id bigserial primary key,
            email text unique,
            pass_hash text, salt text,
            plan text default 'free',
            credits integer default 300,
            created double precision)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS sessions(
            token text primary key,
            user_id bigint references users(id) on delete cascade,
            created double precision)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS configs(
            user_id bigint primary key references users(id) on delete cascade,
            data jsonb)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS signals(
            id bigserial primary key,
            user_id bigint references users(id) on delete cascade,
            external_id text, source text, source_label text, project text,
            author text, text text, url text,
            temp text, strength integer, conf integer,
            why text, hl text, draft text, lang text,
            status text default 'queue',
            ts double precision, created double precision,
            unique(user_id, external_id))""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_signals_user ON signals(user_id, status)")
        conn.commit()
        cur.close(); conn.close()
    else:
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
    if _USE_PG:
        conn = _pg()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users(email,pass_hash,salt,created) VALUES(%s,%s,%s,%s) RETURNING id",
            (email.lower().strip(), pass_hash, salt, time.time()))
        row = cur.fetchone()
        conn.commit(); cur.close(); conn.close()
        return row[0]
    else:
        with _c() as c:
            cur = c.execute(
                "INSERT INTO users(email,pass_hash,salt,created) VALUES(?,?,?,?)",
                (email.lower().strip(), pass_hash, salt, time.time()))
            return cur.lastrowid


def get_user_by_email(email):
    if _USE_PG:
        conn = _pg()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM users WHERE email=%s", (email.lower().strip(),))
        r = cur.fetchone()
        cur.close(); conn.close()
        return dict(r) if r else None
    else:
        with _c() as c:
            r = c.execute("SELECT * FROM users WHERE email=?", (email.lower().strip(),)).fetchone()
            return dict(r) if r else None


def get_user(uid):
    if _USE_PG:
        conn = _pg()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM users WHERE id=%s", (uid,))
        r = cur.fetchone()
        cur.close(); conn.close()
        return dict(r) if r else None
    else:
        with _c() as c:
            r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            return dict(r) if r else None


def set_plan(uid, plan, credits=None):
    if _USE_PG:
        conn = _pg()
        cur = conn.cursor()
        if credits is None:
            cur.execute("UPDATE users SET plan=%s WHERE id=%s", (plan, uid))
        else:
            cur.execute("UPDATE users SET plan=%s, credits=%s WHERE id=%s", (plan, credits, uid))
        conn.commit(); cur.close(); conn.close()
    else:
        with _c() as c:
            if credits is None:
                c.execute("UPDATE users SET plan=? WHERE id=?", (plan, uid))
            else:
                c.execute("UPDATE users SET plan=?, credits=? WHERE id=?", (plan, credits, uid))


def add_credits(uid, delta):
    if _USE_PG:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("UPDATE users SET credits=GREATEST(0,credits+%s) WHERE id=%s", (delta, uid))
        conn.commit(); cur.close(); conn.close()
    else:
        with _c() as c:
            c.execute("UPDATE users SET credits=MAX(0,credits+?) WHERE id=?", (delta, uid))


# ---------- sessions ----------

def create_session(uid, token):
    if _USE_PG:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("INSERT INTO sessions(token,user_id,created) VALUES(%s,%s,%s)", (token, uid, time.time()))
        conn.commit(); cur.close(); conn.close()
    else:
        with _c() as c:
            c.execute("INSERT INTO sessions(token,user_id,created) VALUES(?,?,?)", (token, uid, time.time()))


def session_user(token):
    if not token:
        return None
    if _USE_PG:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM sessions WHERE token=%s", (token,))
        r = cur.fetchone()
        cur.close(); conn.close()
        return r[0] if r else None
    else:
        with _c() as c:
            r = c.execute("SELECT user_id FROM sessions WHERE token=?", (token,)).fetchone()
            return r["user_id"] if r else None


def delete_session(token):
    if _USE_PG:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("DELETE FROM sessions WHERE token=%s", (token,))
        conn.commit(); cur.close(); conn.close()
    else:
        with _c() as c:
            c.execute("DELETE FROM sessions WHERE token=?", (token,))


# ---------- per-user config ----------

def get_config(uid):
    if _USE_PG:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("SELECT data FROM configs WHERE user_id=%s", (uid,))
        r = cur.fetchone()
        cur.close(); conn.close()
        if not r:
            return None
        data = r[0]
        if isinstance(data, str):
            return json.loads(data)
        return data
    else:
        with _c() as c:
            r = c.execute("SELECT data FROM configs WHERE user_id=?", (uid,)).fetchone()
            return json.loads(r["data"]) if r else None


def save_config(uid, cfg):
    if _USE_PG:
        conn = _pg()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO configs(user_id,data) VALUES(%s,%s) "
            "ON CONFLICT(user_id) DO UPDATE SET data=EXCLUDED.data",
            (uid, json.dumps(cfg, ensure_ascii=False)))
        conn.commit(); cur.close(); conn.close()
    else:
        with _c() as c:
            c.execute(
                "INSERT INTO configs(user_id,data) VALUES(?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET data=excluded.data",
                (uid, json.dumps(cfg, ensure_ascii=False)))


# ---------- signals ----------

def exists(uid, external_id):
    if _USE_PG:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM signals WHERE user_id=%s AND external_id=%s", (uid, external_id))
        r = cur.fetchone()
        cur.close(); conn.close()
        return r is not None
    else:
        with _c() as c:
            return c.execute(
                "SELECT 1 FROM signals WHERE user_id=? AND external_id=?",
                (uid, external_id)).fetchone() is not None


def add(uid, post, sig):
    try:
        if _USE_PG:
            conn = _pg()
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO signals
                (user_id,external_id,source,source_label,project,author,text,url,temp,
                 strength,conf,why,hl,draft,lang,status,ts,created)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'queue',%s,%s)
                ON CONFLICT (user_id, external_id) DO NOTHING""",
                (uid, post["external_id"], post["source"], post["source_label"], sig["project"],
                 post.get("author", ""), post["text"], post.get("url", ""), sig["temp"],
                 sig["strength"], sig["conf"], sig["why"],
                 json.dumps(sig.get("hl", []), ensure_ascii=False), sig["draft"],
                 post.get("lang", "en"), post.get("ts", time.time()), time.time()))
            inserted = cur.rowcount > 0
            conn.commit(); cur.close(); conn.close()
            return inserted
        else:
            with _c() as c:
                c.execute(
                    """INSERT OR IGNORE INTO signals
                    (user_id,external_id,source,source_label,project,author,text,url,temp,
                     strength,conf,why,hl,draft,lang,status,ts,created)
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
    if _USE_PG:
        conn = _pg()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if project and project != "all":
            cur.execute(
                "SELECT * FROM signals WHERE user_id=%s AND status='queue' AND project=%s "
                "ORDER BY strength DESC, ts DESC LIMIT 200",
                (uid, project))
        else:
            cur.execute(
                "SELECT * FROM signals WHERE user_id=%s AND status='queue' "
                "ORDER BY strength DESC, ts DESC LIMIT 200",
                (uid,))
        rows = cur.fetchall()
        cur.close(); conn.close()
        out = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("hl"), str):
                d["hl"] = json.loads(d["hl"] or "[]")
            elif d.get("hl") is None:
                d["hl"] = []
            out.append(d)
        return out
    else:
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
    if _USE_PG:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("UPDATE signals SET status=%s WHERE id=%s AND user_id=%s", (status, sid, uid))
        conn.commit(); cur.close(); conn.close()
    else:
        with _c() as c:
            c.execute("UPDATE signals SET status=? WHERE id=? AND user_id=?", (status, sid, uid))


def stats(uid):
    if _USE_PG:
        conn = _pg()
        cur = conn.cursor()
        since = time.time() - 86400
        cur.execute(
            """SELECT
                count(*) FILTER (WHERE status='queue') AS q,
                count(*) FILTER (WHERE status='approved') AS a,
                count(*) FILTER (WHERE status='skipped') AS s,
                count(*) FILTER (WHERE status='queue' AND temp='hot') AS hot,
                count(*) FILTER (WHERE created > %s) AS today
            FROM signals WHERE user_id=%s""",
            (since, uid))
        row = cur.fetchone()
        cur.close(); conn.close()
        return {"queue": row[0] or 0, "approved": row[1] or 0, "skipped": row[2] or 0,
                "hot": row[3] or 0, "today": row[4] or 0}
    else:
        with _c() as c:
            row = c.execute(
                """SELECT
                    SUM(status='queue') q, SUM(status='approved') a, SUM(status='skipped') s,
                    SUM(status='queue' AND temp='hot') hot, SUM(created > ?) today
                FROM signals WHERE user_id=?""",
                (time.time() - 86400, uid)).fetchone()
            return {"queue": row["q"] or 0, "approved": row["a"] or 0, "skipped": row["s"] or 0,
                    "hot": row["hot"] or 0, "today": row["today"] or 0}


def delete_project_signals(uid, pid):
    if _USE_PG:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("DELETE FROM signals WHERE user_id=%s AND project=%s", (uid, pid))
        conn.commit(); cur.close(); conn.close()
    else:
        with _c() as c:
            c.execute("DELETE FROM signals WHERE user_id=? AND project=?", (uid, pid))


def charge(uid, n):
    """Списать n токенов. True если хватило и списали, иначе False."""
    if _USE_PG:
        conn = _pg()
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET credits=credits-%s WHERE id=%s AND credits>=%s",
            (n, uid, n))
        ok = cur.rowcount > 0
        conn.commit(); cur.close(); conn.close()
        return ok
    else:
        with _c() as c:
            r = c.execute("SELECT credits FROM users WHERE id=?", (uid,)).fetchone()
            if not r or r["credits"] < n:
                return False
            c.execute("UPDATE users SET credits=credits-? WHERE id=?", (n, uid))
            return True


def get_signal(uid, sid):
    if _USE_PG:
        conn = _pg()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM signals WHERE id=%s AND user_id=%s", (sid, uid))
        r = cur.fetchone()
        cur.close(); conn.close()
        if not r:
            return None
        d = dict(r)
        if isinstance(d.get("hl"), str):
            d["hl"] = json.loads(d["hl"] or "[]")
        elif d.get("hl") is None:
            d["hl"] = []
        return d
    else:
        with _c() as c:
            r = c.execute(
                "SELECT * FROM signals WHERE id=? AND user_id=?", (sid, uid)).fetchone()
            if not r:
                return None
            d = dict(r); d["hl"] = json.loads(d["hl"] or "[]"); return d


def update_draft(uid, sid, draft):
    if _USE_PG:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("UPDATE signals SET draft=%s WHERE id=%s AND user_id=%s", (draft, sid, uid))
        conn.commit(); cur.close(); conn.close()
    else:
        with _c() as c:
            c.execute("UPDATE signals SET draft=? WHERE id=? AND user_id=?", (draft, sid, uid))


def recent_signals(uid, project, limit=40):
    if _USE_PG:
        conn = _pg(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT text, status FROM signals WHERE user_id=%s AND project=%s ORDER BY created DESC LIMIT %s",
                    (uid, project, limit))
        rows = cur.fetchall(); cur.close(); conn.close()
        return [dict(r) for r in rows]
    with _c() as c:
        rows = c.execute("SELECT text, status FROM signals WHERE user_id=? AND project=? ORDER BY created DESC LIMIT ?",
                         (uid, project, limit)).fetchall()
    return [dict(r) for r in rows]


def export_rows(uid):
    if _USE_PG:
        conn = _pg()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """SELECT source_label, project, temp, strength, conf, text, url, draft, status, created
            FROM signals WHERE user_id=%s ORDER BY created DESC""",
            (uid,))
        rows = cur.fetchall()
        cur.close(); conn.close()
        return [dict(r) for r in rows]
    else:
        with _c() as c:
            rows = c.execute(
                """SELECT source_label, project, temp, strength, conf, text, url, draft, status, created
                FROM signals WHERE user_id=? ORDER BY created DESC""",
                (uid,)).fetchall()
            return [dict(r) for r in rows]


def all_user_ids():
    if _USE_PG:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM configs")
        rows = cur.fetchall()
        cur.close(); conn.close()
        return [r[0] for r in rows]
    else:
        with _c() as c:
            return [r["user_id"] for r in c.execute("SELECT user_id FROM configs").fetchall()]
