from functools import wraps
from datetime import datetime, timedelta, timezone

import jwt
from flask import request, g, jsonify

from constants import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_HOURS, Role
from storage import storage


def generate_token(user):
    payload = {
        "user_id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def _extract_user():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, ("缺少认证信息", 401)
    token = auth_header.split(" ", 1)[1].strip()
    payload = decode_token(token)
    if not payload:
        return None, ("无效或已过期的令牌", 401)
    user = storage.find("users", payload.get("user_id"))
    if not user:
        return None, ("用户不存在", 401)
    return user, None


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user, err = _extract_user()
        if err:
            return jsonify({"code": err[1], "message": err[0]}), err[1]
        g.current_user = user
        return f(*args, **kwargs)
    return wrapper


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user, err = _extract_user()
            if err:
                return jsonify({"code": err[1], "message": err[0]}), err[1]
            if user["role"] not in roles:
                return jsonify({"code": 403, "message": "无权限访问该资源"}), 403
            g.current_user = user
            return f(*args, **kwargs)
        return wrapper
    return decorator


def admin_required(f):
    return role_required(Role.ADMIN)(f)


def inspector_required(f):
    return role_required(Role.INSPECTOR)(f)


def team_lead_required(f):
    return role_required(Role.TEAM_LEAD)(f)


def current_user():
    return getattr(g, "current_user", None)
