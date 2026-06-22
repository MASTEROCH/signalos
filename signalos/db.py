"""db.py — мультитенантное хранилище SaaS. Postgres (psycopg2) если есть DATABASE_URL, иначе SQLite.

Postgres-путь использует ПУЛ соединений: к Supabase-пулеру дорого коннектиться на каждый запрос
(TLS-хендшейк ~100-300мс по сети из Render), поэтому держим тёплые соединения и переиспользуем.
Пул самовосстанавливается: если Supabase уронил простаивающее соединение или Render просыпался
после сна — битый коннект отбрасывается и запрос повторяется на свежем.
"""
import os, json, sqlite3, time, threading

# ---------- backend detection ----------
DATABASE_URL = os.environ.get("DATABASE_URL", "")
_USE_PG = bool(DATABASE_URL)

if _USE_PG:
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool

DB = os.environ.get("LEADOS_DB") or os.environ.get("SIGNALOS_DB") or "leados.db"

# ---------- in-process кэш (один инстанс на Render Free → write-through, когерентно) ----------
# БД (Supabase) в другом регионе, чем Render → каждый запрос к БД ~350мс через Атлантику.
# Тёплый просмотр (конфиг + сессия) держим в памяти → 0 запросов к БД на большинстве ответов.
_USER_TTL = 30          # сек: пользователь (план/кредиты могут устаревать ненадолго — ок)
_cfg_cache = {}         # uid -> JSON-строка конфига (свежая копия на каждое чтение); инвалидация на запись
_user_cache = {}        # token -> (user_dict, expires_at); инвалидация на logout/изменение кредитов/плана
_cache_lock = threading.Lock()


def _users_changed():
    with _cache_lock:
        _user_cache.clear()


# ---------- Postgres: пул соединений ----------
_POOL = None
_POOL_LOCK = threading.Lock()


def _pool():
    global _POOL
    if _POOL is None:
        with _POOL_LOCK:
            if _POOL is None:
                _POOL = psycopg2.pool.ThreadedConnectionPool(
                    1, 20, DATABASE_URL,
                    keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3)
    return _POOL


def _q(sql, args=(), fetch=None, commit=False):
    """Один запрос через пул. fetch: None|'one'|'all'|'rowcount'. Ретрай раз на битом коннекте."""
    last = None
    for _ in (0, 1):
        pool = _pool()
        conn = pool.getconn()
        try:
            if conn.closed:
                raise psycopg2.OperationalError("stale connection")
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(sql, args)
            if fetch == "one":
                out = cur.fetchone()
            elif fetch == "all":
                out = cur.fetchall()
            elif fetch == "rowcount":
                out = cur.rowcount
            else:
                out = None
            if commit:
                conn.commit()
            cur.close()
            pool.putconn(conn)
            return out
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            last = e
            try: pool.putconn(conn, close=True)   # выбросить битый коннект, пул создаст свежий
            except Exception: pass
            continue
        except Exception:
            try: conn.rollback()
            except Exception: pass
            try: pool.putconn(conn)
            except Exception: pass
            raise
    raise last


def _c():
    c = sqlite3.connect(DB, timeout=10); c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL"); return c


_INITED = False


def init():
    global _INITED
    if _INITED:                 # схему создаём один раз на процесс (а не на каждый скан — это 5 cross-region запросов)
        return
    _INITED = True
    if _USE_PG:
        _q("""CREATE TABLE IF NOT EXISTS users(
            id bigserial primary key,
            email text unique,
            pass_hash text, salt text,
            plan text default 'free',
            credits integer default 300,
            created double precision)""", commit=True)
        _q("""CREATE TABLE IF NOT EXISTS sessions(
            token text primary key,
            user_id bigint references users(id) on delete cascade,
            created double precision)""", commit=True)
        _q("""CREATE TABLE IF NOT EXISTS configs(
            user_id bigint primary key references users(id) on delete cascade,
            data jsonb)""", commit=True)
        _q("""CREATE TABLE IF NOT EXISTS signals(
            id bigserial primary key,
            user_id bigint references users(id) on delete cascade,
            external_id text, source text, source_label text, project text,
            author text, text text, url text,
            temp text, strength integer, conf integer,
            why text, hl text, draft text, lang text,
            status text default 'queue',
            ts double precision, created double precision,
            unique(user_id, external_id))""", commit=True)
        _q("CREATE INDEX IF NOT EXISTS idx_signals_user ON signals(user_id, status)", commit=True)
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
        r = _q("INSERT INTO users(email,pass_hash,salt,created) VALUES(%s,%s,%s,%s) RETURNING id",
               (email.lower().strip(), pass_hash, salt, time.time()), fetch="one", commit=True)
        return r["id"]
    else:
        with _c() as c:
            cur = c.execute(
                "INSERT INTO users(email,pass_hash,salt,created) VALUES(?,?,?,?)",
                (email.lower().strip(), pass_hash, salt, time.time()))
            return cur.lastrowid


def get_user_by_email(email):
    if _USE_PG:
        r = _q("SELECT * FROM users WHERE email=%s", (email.lower().strip(),), fetch="one")
        return dict(r) if r else None
    else:
        with _c() as c:
            r = c.execute("SELECT * FROM users WHERE email=?", (email.lower().strip(),)).fetchone()
            return dict(r) if r else None


def get_user(uid):
    if _USE_PG:
        r = _q("SELECT * FROM users WHERE id=%s", (uid,), fetch="one")
        return dict(r) if r else None
    else:
        with _c() as c:
            r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            return dict(r) if r else None


def set_plan(uid, plan, credits=None):
    if _USE_PG:
        if credits is None:
            _q("UPDATE users SET plan=%s WHERE id=%s", (plan, uid), commit=True)
        else:
            _q("UPDATE users SET plan=%s, credits=%s WHERE id=%s", (plan, credits, uid), commit=True)
    else:
        with _c() as c:
            if credits is None:
                c.execute("UPDATE users SET plan=? WHERE id=?", (plan, uid))
            else:
                c.execute("UPDATE users SET plan=?, credits=? WHERE id=?", (plan, credits, uid))
    _users_changed()


def add_credits(uid, delta):
    if _USE_PG:
        _q("UPDATE users SET credits=GREATEST(0,credits+%s) WHERE id=%s", (delta, uid), commit=True)
    else:
        with _c() as c:
            c.execute("UPDATE users SET credits=MAX(0,credits+?) WHERE id=?", (delta, uid))
    _users_changed()


# ---------- sessions ----------

def create_session(uid, token):
    if _USE_PG:
        _q("INSERT INTO sessions(token,user_id,created) VALUES(%s,%s,%s)", (token, uid, time.time()), commit=True)
    else:
        with _c() as c:
            c.execute("INSERT INTO sessions(token,user_id,created) VALUES(?,?,?)", (token, uid, time.time()))


def session_user(token):
    if not token:
        return None
    if _USE_PG:
        r = _q("SELECT user_id FROM sessions WHERE token=%s", (token,), fetch="one")
        return r["user_id"] if r else None
    else:
        with _c() as c:
            r = c.execute("SELECT user_id FROM sessions WHERE token=?", (token,)).fetchone()
            return r["user_id"] if r else None


def user_for_session(token):
    """Сессия + пользователь одним запросом (быстрый путь авторизации). Кэш на _USER_TTL сек."""
    if not token:
        return None
    now = time.time()
    with _cache_lock:
        e = _user_cache.get(token)
        if e and e[1] > now:
            return dict(e[0])
    if _USE_PG:
        r = _q("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=%s",
               (token,), fetch="one")
        u = dict(r) if r else None
    else:
        with _c() as c:
            r = c.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?",
                          (token,)).fetchone()
            u = dict(r) if r else None
    if u:
        with _cache_lock:
            _user_cache[token] = (dict(u), now + _USER_TTL)
    return u


def delete_session(token):
    with _cache_lock:
        _user_cache.pop(token, None)
    if _USE_PG:
        _q("DELETE FROM sessions WHERE token=%s", (token,), commit=True)
    else:
        with _c() as c:
            c.execute("DELETE FROM sessions WHERE token=?", (token,))


# ---------- per-user config ----------

def get_config(uid):
    with _cache_lock:
        if uid in _cfg_cache:
            s = _cfg_cache[uid]
            return json.loads(s) if s is not None else None        # свежая копия — каллеры мутируют
    if _USE_PG:
        r = _q("SELECT data FROM configs WHERE user_id=%s", (uid,), fetch="one")
        data = (r["data"] if r else None)
        cfg = (json.loads(data) if isinstance(data, str) else data) if r else None
    else:
        with _c() as c:
            r = c.execute("SELECT data FROM configs WHERE user_id=?", (uid,)).fetchone()
            cfg = json.loads(r["data"]) if r else None
    with _cache_lock:
        _cfg_cache[uid] = json.dumps(cfg, ensure_ascii=False) if cfg is not None else None
    return cfg


def save_config(uid, cfg):
    s = json.dumps(cfg, ensure_ascii=False)
    if _USE_PG:
        _q("INSERT INTO configs(user_id,data) VALUES(%s,%s) "
           "ON CONFLICT(user_id) DO UPDATE SET data=EXCLUDED.data", (uid, s), commit=True)
    else:
        with _c() as c:
            c.execute(
                "INSERT INTO configs(user_id,data) VALUES(?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET data=excluded.data", (uid, s))
    with _cache_lock:
        _cfg_cache[uid] = s        # write-through


# ---------- signals ----------

def exists(uid, external_id):
    if _USE_PG:
        return _q("SELECT 1 FROM signals WHERE user_id=%s AND external_id=%s",
                  (uid, external_id), fetch="one") is not None
    else:
        with _c() as c:
            return c.execute(
                "SELECT 1 FROM signals WHERE user_id=? AND external_id=?",
                (uid, external_id)).fetchone() is not None


def existing_ids(uid):
    """Все external_id пользователя одним запросом — дедуп в памяти вместо запроса на каждый пост."""
    if _USE_PG:
        rows = _q("SELECT external_id FROM signals WHERE user_id=%s", (uid,), fetch="all")
        return {r["external_id"] for r in rows}
    else:
        with _c() as c:
            return {r["external_id"] for r in
                    c.execute("SELECT external_id FROM signals WHERE user_id=?", (uid,)).fetchall()}


def add(uid, post, sig):
    try:
        if _USE_PG:
            rc = _q(
                """INSERT INTO signals
                (user_id,external_id,source,source_label,project,author,text,url,temp,
                 strength,conf,why,hl,draft,lang,status,ts,created)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'queue',%s,%s)
                ON CONFLICT (user_id, external_id) DO NOTHING""",
                (uid, post["external_id"], post["source"], post["source_label"], sig["project"],
                 post.get("author", ""), post["text"], post.get("url", ""), sig["temp"],
                 sig["strength"], sig["conf"], sig["why"],
                 json.dumps(sig.get("hl", []), ensure_ascii=False), sig["draft"],
                 post.get("lang", "en"), post.get("ts", time.time()), time.time()),
                fetch="rowcount", commit=True)
            return rc > 0
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


def _parse_hl(d):
    if isinstance(d.get("hl"), str):
        d["hl"] = json.loads(d["hl"] or "[]")
    elif d.get("hl") is None:
        d["hl"] = []
    return d


def queue(uid, project=None):
    if _USE_PG:
        if project and project != "all":
            rows = _q("SELECT * FROM signals WHERE user_id=%s AND status='queue' AND project=%s "
                      "ORDER BY strength DESC, ts DESC LIMIT 200", (uid, project), fetch="all")
        else:
            rows = _q("SELECT * FROM signals WHERE user_id=%s AND status='queue' "
                      "ORDER BY strength DESC, ts DESC LIMIT 200", (uid,), fetch="all")
        return [_parse_hl(dict(r)) for r in rows]
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
        _q("UPDATE signals SET status=%s WHERE id=%s AND user_id=%s", (status, sid, uid), commit=True)
    else:
        with _c() as c:
            c.execute("UPDATE signals SET status=? WHERE id=? AND user_id=?", (status, sid, uid))


def stats(uid):
    if _USE_PG:
        since = time.time() - 86400
        row = _q(
            """SELECT
                count(*) FILTER (WHERE status='queue') AS q,
                count(*) FILTER (WHERE status='approved') AS a,
                count(*) FILTER (WHERE status='skipped') AS s,
                count(*) FILTER (WHERE status='queue' AND temp='hot') AS hot,
                count(*) FILTER (WHERE created > %s) AS today
            FROM signals WHERE user_id=%s""",
            (since, uid), fetch="one")
        return {"queue": row["q"] or 0, "approved": row["a"] or 0, "skipped": row["s"] or 0,
                "hot": row["hot"] or 0, "today": row["today"] or 0}
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
        _q("DELETE FROM signals WHERE user_id=%s AND project=%s", (uid, pid), commit=True)
    else:
        with _c() as c:
            c.execute("DELETE FROM signals WHERE user_id=? AND project=?", (uid, pid))


def charge(uid, n):
    """Списать n токенов. True если хватило и списали, иначе False."""
    if _USE_PG:
        rc = _q("UPDATE users SET credits=credits-%s WHERE id=%s AND credits>=%s",
                (n, uid, n), fetch="rowcount", commit=True)
        if rc > 0:
            _users_changed()
        return rc > 0
    else:
        with _c() as c:
            r = c.execute("SELECT credits FROM users WHERE id=?", (uid,)).fetchone()
            if not r or r["credits"] < n:
                return False
            c.execute("UPDATE users SET credits=credits-? WHERE id=?", (n, uid))
        _users_changed()
        return True


def get_signal(uid, sid):
    if _USE_PG:
        r = _q("SELECT * FROM signals WHERE id=%s AND user_id=%s", (sid, uid), fetch="one")
        return _parse_hl(dict(r)) if r else None
    else:
        with _c() as c:
            r = c.execute(
                "SELECT * FROM signals WHERE id=? AND user_id=?", (sid, uid)).fetchone()
            if not r:
                return None
            d = dict(r); d["hl"] = json.loads(d["hl"] or "[]"); return d


def update_draft(uid, sid, draft):
    if _USE_PG:
        _q("UPDATE signals SET draft=%s WHERE id=%s AND user_id=%s", (draft, sid, uid), commit=True)
    else:
        with _c() as c:
            c.execute("UPDATE signals SET draft=? WHERE id=? AND user_id=?", (draft, sid, uid))


def recent_signals(uid, project, limit=40):
    if _USE_PG:
        rows = _q("SELECT text, status FROM signals WHERE user_id=%s AND project=%s "
                  "ORDER BY created DESC LIMIT %s", (uid, project, limit), fetch="all")
        return [dict(r) for r in rows]
    with _c() as c:
        rows = c.execute("SELECT text, status FROM signals WHERE user_id=? AND project=? ORDER BY created DESC LIMIT ?",
                         (uid, project, limit)).fetchall()
    return [dict(r) for r in rows]


def digest_signals(uid, since, min_strength, limit=6):
    """Свежие искры для утреннего дайджеста: в очереди, найдены после `since`, резонанс>=min."""
    if _USE_PG:
        rows = _q(
            """SELECT id, project, source_label, text, url, draft, strength, why, temp, created
            FROM signals WHERE user_id=%s AND status='queue' AND strength>=%s AND created>%s
            ORDER BY strength DESC, created DESC LIMIT %s""",
            (uid, min_strength, since, limit), fetch="all")
        return [dict(r) for r in rows]
    else:
        with _c() as c:
            rows = c.execute(
                """SELECT id, project, source_label, text, url, draft, strength, why, temp, created
                FROM signals WHERE user_id=? AND status='queue' AND strength>=? AND created>?
                ORDER BY strength DESC, created DESC LIMIT ?""",
                (uid, min_strength, since, limit)).fetchall()
            return [dict(r) for r in rows]


def export_rows(uid):
    if _USE_PG:
        rows = _q(
            """SELECT source_label, project, temp, strength, conf, text, url, draft, status, created
            FROM signals WHERE user_id=%s ORDER BY created DESC""", (uid,), fetch="all")
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
        rows = _q("SELECT user_id FROM configs", fetch="all")
        return [r["user_id"] for r in rows]
    else:
        with _c() as c:
            return [r["user_id"] for r in c.execute("SELECT user_id FROM configs").fetchall()]
