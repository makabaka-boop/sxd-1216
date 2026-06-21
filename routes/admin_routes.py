from flask import Blueprint

from auth import admin_required
from constants import Role
from storage import storage, gen_id, now_iso
from utils import ok, fail, get_json_body, parse_args, name_of

bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def _enrich_business_line(bl):
    bl["responsible_person"] = bl.get("responsible_person")
    return bl


@bp.get("/business-lines")
@admin_required
def list_business_lines():
    items = storage.read("business_lines")
    return ok(items)


@bp.post("/business-lines")
@admin_required
def create_business_line():
    body = get_json_body()
    name = (body.get("name") or "").strip()
    if not name:
        return fail("业务线名称不能为空")
    if storage.find_one("business_lines", lambda b: b["name"] == name):
        return fail("业务线名称已存在")
    record = {
        "id": gen_id("bl"),
        "name": name,
        "responsible_person": body.get("responsible_person"),
        "created_at": now_iso(),
    }
    storage.insert("business_lines", record)
    return ok(record, "创建成功")


@bp.put("/business-lines/<record_id>")
@admin_required
def update_business_line(record_id):
    body = get_json_body()
    patch = {}
    if body.get("name"):
        patch["name"] = body["name"].strip()
    if "responsible_person" in body:
        patch["responsible_person"] = body.get("responsible_person")
    rec = storage.update("business_lines", record_id, patch)
    if not rec:
        return fail("业务线不存在", 404)
    return ok(rec, "更新成功")


@bp.delete("/business-lines/<record_id>")
@admin_required
def delete_business_line(record_id):
    data = storage.read("business_lines")
    new_data = [r for r in data if r["id"] != record_id]
    if len(new_data) == len(data):
        return fail("业务线不存在", 404)
    storage.write("business_lines", new_data)
    return ok(None, "删除成功")


@bp.get("/seat-groups")
@admin_required
def list_seat_groups():
    args = parse_args()
    items = storage.read("seat_groups")
    if args.get("business_line_id"):
        items = [s for s in items if s.get("business_line_id") == args["business_line_id"]]
    for s in items:
        s["business_line_name"] = name_of("business_lines", s.get("business_line_id"))
        s["leader_name"] = name_of("users", s.get("leader_id"), "name")
    return ok(items)


@bp.post("/seat-groups")
@admin_required
def create_seat_group():
    body = get_json_body()
    name = (body.get("name") or "").strip()
    if not name:
        return fail("坐席组名称不能为空")
    record = {
        "id": gen_id("sg"),
        "name": name,
        "business_line_id": body.get("business_line_id"),
        "leader_id": body.get("leader_id"),
        "created_at": now_iso(),
    }
    storage.insert("seat_groups", record)
    record["business_line_name"] = name_of("business_lines", record.get("business_line_id"))
    record["leader_name"] = name_of("users", record.get("leader_id"), "name")
    return ok(record, "创建成功")


@bp.put("/seat-groups/<record_id>")
@admin_required
def update_seat_group(record_id):
    body = get_json_body()
    patch = {k: body[k] for k in ("name", "business_line_id", "leader_id") if k in body}
    rec = storage.update("seat_groups", record_id, patch)
    if not rec:
        return fail("坐席组不存在", 404)
    rec["business_line_name"] = name_of("business_lines", rec.get("business_line_id"))
    rec["leader_name"] = name_of("users", rec.get("leader_id"), "name")
    return ok(rec, "更新成功")


@bp.delete("/seat-groups/<record_id>")
@admin_required
def delete_seat_group(record_id):
    data = storage.read("seat_groups")
    new_data = [r for r in data if r["id"] != record_id]
    if len(new_data) == len(data):
        return fail("坐席组不存在", 404)
    storage.write("seat_groups", new_data)
    return ok(None, "删除成功")


@bp.get("/scoring-tables")
@admin_required
def list_scoring_tables():
    args = parse_args()
    items = storage.read("scoring_tables")
    if args.get("business_line_id"):
        items = [s for s in items if s.get("business_line_id") == args["business_line_id"]]
    for s in items:
        s["business_line_name"] = name_of("business_lines", s.get("business_line_id"))
    return ok(items)


@bp.post("/scoring-tables")
@admin_required
def create_scoring_table():
    body = get_json_body()
    name = (body.get("name") or "").strip()
    if not name:
        return fail("评分表名称不能为空")
    items = body.get("items") or []
    total = body.get("total_score")
    if total is None:
        total = sum(float(i.get("max_score", 0)) for i in items)
    record = {
        "id": gen_id("st"),
        "name": name,
        "business_line_id": body.get("business_line_id"),
        "total_score": total,
        "items": items,
        "created_at": now_iso(),
    }
    storage.insert("scoring_tables", record)
    record["business_line_name"] = name_of("business_lines", record.get("business_line_id"))
    return ok(record, "创建成功")


@bp.put("/scoring-tables/<record_id>")
@admin_required
def update_scoring_table(record_id):
    body = get_json_body()
    patch = {}
    if body.get("name"):
        patch["name"] = body["name"].strip()
    if "business_line_id" in body:
        patch["business_line_id"] = body.get("business_line_id")
    if "items" in body:
        patch["items"] = body.get("items") or []
    if "total_score" in body:
        patch["total_score"] = body.get("total_score")
    elif "items" in patch:
        patch["total_score"] = sum(float(i.get("max_score", 0)) for i in patch["items"])
    rec = storage.update("scoring_tables", record_id, patch)
    if not rec:
        return fail("评分表不存在", 404)
    rec["business_line_name"] = name_of("business_lines", rec.get("business_line_id"))
    return ok(rec, "更新成功")


@bp.delete("/scoring-tables/<record_id>")
@admin_required
def delete_scoring_table(record_id):
    data = storage.read("scoring_tables")
    new_data = [r for r in data if r["id"] != record_id]
    if len(new_data) == len(data):
        return fail("评分表不存在", 404)
    storage.write("scoring_tables", new_data)
    return ok(None, "删除成功")


@bp.get("/config")
@admin_required
def get_config():
    cfg = storage.read("config") or {}
    return ok(cfg)


@bp.put("/config")
@admin_required
def update_config():
    body = get_json_body()
    cfg = storage.read("config") or {}
    for k in ("sampling_ratio", "appeal_deadline_hours", "review_deadline_hours",
              "low_score_threshold", "risk_low_score_ratio", "risk_min_sample"):
        if k in body:
            cfg[k] = body[k]
    storage.write("config", cfg)
    return ok(cfg, "配置已更新")


@bp.get("/users")
@admin_required
def list_users():
    args = parse_args()
    items = storage.read("users")
    if args.get("role"):
        items = [u for u in items if u["role"] == args["role"]]
    safe = [{k: v for k, v in u.items() if k != "password"} for u in items]
    for u in safe:
        u["business_line_name"] = name_of("business_lines", u.get("business_line_id"))
        u["seat_group_name"] = name_of("seat_groups", u.get("seat_group_id"))
    return ok(safe)


@bp.post("/users")
@admin_required
def create_user():
    body = get_json_body()
    username = (body.get("username") or "").strip()
    if not username:
        return fail("用户名不能为空")
    if not body.get("password"):
        return fail("密码不能为空")
    role = body.get("role")
    if role not in Role.ALL:
        return fail("角色无效，可选: admin/inspector/team_lead")
    if storage.find_one("users", lambda u: u["username"] == username):
        return fail("用户名已存在")
    record = {
        "id": gen_id("u"),
        "username": username,
        "password": body["password"],
        "role": role,
        "name": body.get("name") or username,
        "business_line_id": body.get("business_line_id"),
        "seat_group_id": body.get("seat_group_id"),
        "created_at": now_iso(),
    }
    storage.insert("users", record)
    record.pop("password", None)
    return ok(record, "创建成功")


@bp.put("/users/<record_id>")
@admin_required
def update_user(record_id):
    body = get_json_body()
    patch = {}
    for k in ("name", "role", "business_line_id", "seat_group_id"):
        if k in body:
            patch[k] = body[k]
    if body.get("password"):
        patch["password"] = body["password"]
    rec = storage.update("users", record_id, patch)
    if not rec:
        return fail("用户不存在", 404)
    rec.pop("password", None)
    return ok(rec, "更新成功")


@bp.delete("/users/<record_id>")
@admin_required
def delete_user(record_id):
    data = storage.read("users")
    new_data = [r for r in data if r["id"] != record_id]
    if len(new_data) == len(data):
        return fail("用户不存在", 404)
    storage.write("users", new_data)
    return ok(None, "删除成功")
