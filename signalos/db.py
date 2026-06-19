"""db.py — SQLite-хранилище сигналов с дедупом по external_id."""
import os, json, sqlite3, time

DB = os.environ.get("SIGNALOS_DB", "signalos.db")


def _c():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c


def init():
    with _c() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS signals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            external_id TEXT UNIQUE, source TEXT, source_label TEXT,
            project TEXT, author TEXT, text TEXT, url TEXT,
            temp TEXT, strength INTEGER, conf INTEGER,
            why TEXT, hl TEXT, draft TEXT, lang TEXT,
            status TEXT DEFAULT 'queue',     -- queue | approved | skipped
            ts REAL, created REAL)""")


def exists(external_id):
    with _c() as c:
        return c.execute("SELECT 1 FROM signals WHERE external_id=?", (external_id,)).fetchone() is not None


def add(post, sig):
    try:
        with _c() as c:
            c.execute("""INSERT OR IGNORE INTO signals
                (external_id,source,source_label,project,author,text,url,temp,strength,conf,why,hl,draft,lang,status,ts,created)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'queue',?,?)""",
                (post["external_id"], post["source"], post["source_label"], sig["project"],
                 post.get("author", ""), post["text"], post.get("url", ""), sig["temp"],
                 sig["strength"], sig["conf"], sig["why"], json.dumps(sig.get("hl", []), ensure_ascii=False),
                 sig["draft"], post.get("lang", "en"), post.get("ts", time.time()), time.time()))
            return c.total_changes > 0
    except Exception:
        return False


def queue(project=None):
    q = "SELECT * FROM signals WHERE status='queue'"; a = []
    if project and project != "all":
        q += " AND project=?"; a.append(project)
    q += " ORDER BY strength DESC, ts DESC LIMIT 200"
    with _c() as c:
        rows = c.execute(q, a).fetchall()
    out = []
    for r in rows:
        d = dict(r); d["hl"] = json.loads(d["hl"] or "[]"); out.append(d)
    return out


def set_status(sid, status):
    with _c() as c:
        c.execute("UPDATE signals SET status=? WHERE id=?", (status, sid))


def stats():
    with _c() as c:
        row = c.execute("""SELECT
            SUM(status='queue') q, SUM(status='approved') a, SUM(status='skipped') s,
            SUM(status='queue' AND temp='hot') hot,
            SUM(ts > ?) today FROM signals""", (time.time() - 86400,)).fetchone()
    return {"queue": row["q"] or 0, "approved": row["a"] or 0, "skipped": row["s"] or 0,
            "hot": row["hot"] or 0, "today": row["today"] or 0}
