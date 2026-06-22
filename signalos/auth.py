"""auth.py — регистрация, вход, сессии. Пароли через pbkdf2 (stdlib, без зависимостей)."""
import hashlib, secrets, re
from . import db

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()


def register(email, password):
    email = (email or "").lower().strip()
    if not EMAIL_RE.match(email):
        return {"error": "Введи корректный email"}
    if len(password or "") < 6:
        return {"error": "Пароль минимум 6 символов"}
    if db.get_user_by_email(email):
        return {"error": "Такой email уже зарегистрирован — войди"}
    salt = secrets.token_hex(16)
    uid = db.create_user(email, _hash(password, salt), salt)
    token = _new_session(uid)
    return {"ok": True, "token": token, "user": _safe_user(db.get_user(uid))}


def login(email, password):
    u = db.get_user_by_email((email or "").lower().strip())
    if not u or _hash(password or "", u["salt"]) != u["pass_hash"]:
        return {"error": "Неверный email или пароль"}
    token = _new_session(u["id"])
    return {"ok": True, "token": token, "user": _safe_user(u)}


def logout(token):
    db.delete_session(token)
    return {"ok": True}


def current_user(token):
    return db.user_for_session(token)   # сессия+юзер одним запросом


def _new_session(uid):
    token = secrets.token_urlsafe(32)
    db.create_session(uid, token)
    return token


def _safe_user(u):
    return {"id": u["id"], "email": u["email"], "plan": u["plan"], "credits": u["credits"]}
