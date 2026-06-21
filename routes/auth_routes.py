from flask import Blueprint, g

from auth import generate_token, login_required
from constants import Role
from storage import storage
from utils import ok, fail, get_json_body

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _public_user(user):
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "name": user.get("name"),
        "business_line_id": user.get("business_line_id"),
        "seat_group_id": user.get("seat_group_id"),
    }


@bp.post("/login")
def login():
    body = get_json_body()
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        return fail("用户名和密码不能为空")
    user = storage.find_one("users", lambda u: u["username"] == username)
    if not user or user.get("password") != password:
        return fail("用户名或密码错误", 401)
    token = generate_token(user)
    return ok({"token": token, "user": _public_user(user)}, "登录成功")


@bp.get("/me")
@login_required
def me():
    return ok(_public_user(g.current_user))


@bp.get("/roles")
def roles():
    return ok([{"value": r, "label": Role.LABELS[r]} for r in Role.ALL])
