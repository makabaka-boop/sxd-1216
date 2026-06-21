from flask import Blueprint, g

from auth import inspector_required, login_required
from constants import Status
from storage import storage, gen_id, now_iso
from utils import ok, fail, get_json_body, parse_args, paginate
from inspection_common import compute_total_score, get_scoring_table, enrich_inspection

bp = Blueprint("inspector", __name__, url_prefix="/api/inspector")


def _has_active_inspection(call_id, exclude_id=None):
    return storage.find_one("inspections", lambda i: (
        i.get("call_id") == call_id
        and i.get("id") != exclude_id
    ))


@bp.get("/inspections")
@inspector_required
def list_inspections():
    args = parse_args()
    items = storage.find_all("inspections", lambda i: i.get("inspector_id") == g.current_user["id"])
    if args.get("status"):
        items = [i for i in items if i.get("status") == args["status"]]
    items.sort(key=lambda i: i.get("created_at", ""), reverse=True)
    for i in items:
        enrich_inspection(i)
    return ok(paginate(items, args.get("page"), args.get("page_size")))


@bp.post("/inspections")
@inspector_required
def create_inspection():
    body = get_json_body()
    call_id = (body.get("call_id") or "").strip()
    if not call_id:
        return fail("通话编号不能为空")
    if _has_active_inspection(call_id):
        return fail("该通话已存在抽检记录，避免重复抽检", 409)
    scoring_table_id = body.get("scoring_table_id")
    if not scoring_table_id:
        table = storage.find_one("scoring_tables", lambda s: True)
        scoring_table_id = table["id"] if table else None
    record = {
        "id": gen_id("ins"),
        "call_id": call_id,
        "business_line_id": body.get("business_line_id"),
        "seat_group_id": body.get("seat_group_id"),
        "agent_name": body.get("agent_name"),
        "inspector_id": g.current_user["id"],
        "scoring_table_id": scoring_table_id,
        "status": Status.PENDING_INSPECTION,
        "deductions": [],
        "service_language_issues": None,
        "suggestion": None,
        "relisten": False,
        "total_score": None,
        "created_at": now_iso(),
        "inspected_at": None,
        "submitted_at": None,
    }
    storage.insert("inspections", record)
    enrich_inspection(record)
    return ok(record, "已创建抽检记录")


@bp.post("/inspections/<record_id>/start")
@inspector_required
def start_inspection(record_id):
    insp = storage.find("inspections", record_id)
    if not insp:
        return fail("抽检记录不存在", 404)
    if insp["status"] != Status.PENDING_INSPECTION:
        return fail("当前状态无法开始质检")
    owner = insp.get("inspector_id")
    me = g.current_user["id"]
    if owner and owner != me:
        return fail("该抽检记录已分配给其他质检员，您无权处理", 403)
    insp = storage.update("inspections", record_id, {
        "status": Status.INSPECTING,
        "inspector_id": me,
        "inspected_at": now_iso(),
    })
    enrich_inspection(insp)
    return ok(insp, "已开始质检")


@bp.post("/inspections/<record_id>/submit")
@inspector_required
def submit_inspection(record_id):
    body = get_json_body()
    insp = storage.find("inspections", record_id)
    if not insp:
        return fail("抽检记录不存在", 404)
    me = g.current_user["id"]
    if insp.get("inspector_id") and insp["inspector_id"] != me:
        return fail("该抽检记录归属其他质检员，您无权提交", 403)
    if insp["status"] not in (Status.PENDING_INSPECTION, Status.INSPECTING):
        return fail("当前状态无法提交质检结果")
    deductions = body.get("deductions") or []
    table = get_scoring_table(insp)
    if table:
        valid_ids = {it["id"] for it in table.get("items", [])}
        for d in deductions:
            item_id = d.get("item_id")
            item = next((it for it in table.get("items", []) if it["id"] == item_id), None)
            if item:
                d["item_name"] = item.get("name")
                d["max_score"] = item.get("max_score")
                if float(d.get("deducted", 0) or 0) > float(item.get("max_score", 0) or 0):
                    return fail(f"扣分超过上限：{item.get('name')}")
            else:
                d["item_name"] = d.get("item_name") or item_id
    total_score = compute_total_score(table, deductions)
    patch = {
        "status": Status.PENDING_APPEAL,
        "deductions": deductions,
        "service_language_issues": body.get("service_language_issues"),
        "suggestion": body.get("suggestion"),
        "relisten": bool(body.get("relisten", False)),
        "total_score": total_score,
        "inspector_id": me,
        "inspected_at": insp.get("inspected_at") or now_iso(),
        "submitted_at": now_iso(),
    }
    insp = storage.update("inspections", record_id, patch)
    enrich_inspection(insp)
    return ok(insp, "质检结果已提交，等待申诉")


@bp.get("/scoring-tables")
@login_required
def list_scoring_tables():
    items = storage.read("scoring_tables")
    return ok(items)
