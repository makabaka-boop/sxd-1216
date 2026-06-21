from datetime import datetime, timedelta, timezone

from flask import Blueprint, g

from auth import team_lead_required, login_required, role_required, admin_required
from constants import Status, Role
from storage import storage, gen_id, now_iso
from utils import ok, fail, get_json_body, parse_args, paginate, name_of
from inspection_common import enrich_appeal

bp = Blueprint("appeal", __name__, url_prefix="/api/appeals")


def _deadline_hours():
    cfg = storage.read("config") or {}
    return int(cfg.get("appeal_deadline_hours", 48))


def _compute_deadline():
    return (datetime.now(timezone.utc) + timedelta(hours=_deadline_hours())).isoformat(timespec="seconds")


@bp.post("")
@team_lead_required
def submit_appeal():
    body = get_json_body()
    inspection_id = body.get("inspection_id")
    insp = storage.find("inspections", inspection_id) if inspection_id else None
    if not insp:
        return fail("抽检记录不存在", 404)
    if insp["status"] != Status.PENDING_APPEAL:
        return fail("该记录当前状态不可申诉")
    existing = storage.find_one("appeals", lambda a: a.get("inspection_id") == inspection_id)
    if existing:
        return fail("该记录已提交过申诉", 409)
    reason = (body.get("reason") or "").strip()
    if not reason:
        return fail("申诉理由不能为空")
    appeal = {
        "id": gen_id("ap"),
        "inspection_id": inspection_id,
        "team_lead_id": g.current_user["id"],
        "reason": reason,
        "evidence_link": body.get("evidence_link"),
        "adjustment_request": body.get("adjustment_request"),
        "close_note": None,
        "deadline": _compute_deadline(),
        "created_at": now_iso(),
        "closed_at": None,
    }
    storage.insert("appeals", appeal)
    storage.update("inspections", inspection_id, {"status": Status.APPEAL_PROCESSING})
    enrich_appeal(appeal)
    return ok(appeal, "申诉已提交")


@bp.get("")
@login_required
def list_appeals():
    args = parse_args()
    user = g.current_user
    items = storage.read("appeals")
    if user["role"] == Role.TEAM_LEAD:
        items = [a for a in items if a.get("team_lead_id") == user["id"]]
    if args.get("inspection_id"):
        items = [a for a in items if a.get("inspection_id") == args["inspection_id"]]
    if args.get("overdue") in ("1", "true", "True"):
        now = now_iso()
        items = [a for a in items if a.get("deadline") and a.get("deadline") < now and not a.get("closed_at")]
    items.sort(key=lambda a: a.get("created_at", ""), reverse=True)
    for a in items:
        enrich_appeal(a)
    return ok(paginate(items, args.get("page"), args.get("page_size")))


@bp.get("/<record_id>")
@login_required
def get_appeal(record_id):
    appeal = storage.find("appeals", record_id)
    if not appeal:
        return fail("申诉不存在", 404)
    enrich_appeal(appeal)
    return ok(appeal)


@bp.put("/<record_id>")
@team_lead_required
def adjust_appeal(record_id):
    body = get_json_body()
    appeal = storage.find("appeals", record_id)
    if not appeal:
        return fail("申诉不存在", 404)
    if appeal.get("team_lead_id") != g.current_user["id"] and g.current_user["role"] != Role.ADMIN:
        return fail("无权修改该申诉", 403)
    insp = storage.find("inspections", appeal["inspection_id"])
    if not insp or insp["status"] != Status.APPEAL_PROCESSING:
        return fail("申诉当前状态不可调整")
    patch = {}
    for k in ("reason", "evidence_link", "adjustment_request"):
        if k in body:
            patch[k] = body.get(k)
    appeal = storage.update("appeals", record_id, patch)
    enrich_appeal(appeal)
    return ok(appeal, "申诉已更新")


@bp.post("/<record_id>/request-review")
@team_lead_required
def request_review(record_id):
    appeal = storage.find("appeals", record_id)
    if not appeal:
        return fail("申诉不存在", 404)
    insp = storage.find("inspections", appeal["inspection_id"])
    if not insp or insp["status"] != Status.APPEAL_PROCESSING:
        return fail("申诉当前状态不可提交复核")
    insp = storage.update("inspections", appeal["inspection_id"], {"status": Status.PENDING_REVIEW})
    from inspection_common import enrich_inspection
    enrich_inspection(insp)
    return ok(insp, "已提交复核")


@bp.post("/<record_id>/close")
@team_lead_required
def close_appeal(record_id):
    body = get_json_body()
    appeal = storage.find("appeals", record_id)
    if not appeal:
        return fail("申诉不存在", 404)
    insp = storage.find("inspections", appeal["inspection_id"])
    if not insp or insp["status"] not in (Status.APPEAL_PROCESSING, Status.PENDING_REVIEW):
        return fail("申诉当前状态不可结案")
    appeal = storage.update("appeals", record_id, {
        "close_note": body.get("close_note"),
        "closed_at": now_iso(),
    })
    storage.update("inspections", appeal["inspection_id"], {"status": Status.CLOSED})
    enrich_appeal(appeal)
    return ok(appeal, "申诉已结案")
