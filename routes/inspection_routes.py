from flask import Blueprint, g

from auth import login_required, admin_required
from constants import Status
from storage import storage
from utils import ok, fail, parse_args, paginate, get_json_body
from inspection_common import enrich_inspection

bp = Blueprint("inspection", __name__, url_prefix="/api/inspections")


@bp.get("")
@login_required
def list_inspections():
    args = parse_args()
    items = storage.read("inspections")

    if args.get("business_line_id"):
        items = [i for i in items if i.get("business_line_id") == args["business_line_id"]]
    if args.get("seat_group_id"):
        items = [i for i in items if i.get("seat_group_id") == args["seat_group_id"]]
    if args.get("inspector_id"):
        items = [i for i in items if i.get("inspector_id") == args["inspector_id"]]
    if args.get("call_id"):
        items = [i for i in items if i.get("call_id") == args["call_id"]]
    if args.get("status"):
        statuses = args["status"].split(",")
        items = [i for i in items if i.get("status") in statuses]
    if args.get("score_min") is not None and args.get("score_min") != "":
        try:
            score_min = float(args["score_min"])
            items = [i for i in items if i.get("total_score") is not None and i["total_score"] >= score_min]
        except ValueError:
            return fail("score_min 必须为数字")
    if args.get("score_max") is not None and args.get("score_max") != "":
        try:
            score_max = float(args["score_max"])
            items = [i for i in items if i.get("total_score") is not None and i["total_score"] <= score_max]
        except ValueError:
            return fail("score_max 必须为数字")
    if args.get("start_date"):
        items = [i for i in items if i.get("created_at", "") >= args["start_date"]]
    if args.get("end_date"):
        items = [i for i in items if i.get("created_at", "") <= args["end_date"]]

    items.sort(key=lambda i: i.get("created_at", ""), reverse=True)
    for i in items:
        enrich_inspection(i)
    return ok(paginate(items, args.get("page"), args.get("page_size")))


@bp.get("/statuses")
@login_required
def statuses():
    return ok([{"value": s, "label": Status.LABELS[s]} for s in Status.ALL])


@bp.get("/<record_id>")
@login_required
def get_inspection(record_id):
    insp = storage.find("inspections", record_id)
    if not insp:
        return fail("抽检记录不存在", 404)
    enrich_inspection(insp)
    appeal = storage.find_one("appeals", lambda a: a.get("inspection_id") == record_id)
    review = storage.find_one("reviews", lambda r: r.get("inspection_id") == record_id)
    return ok({"inspection": insp, "appeal": appeal, "review": review})


@bp.put("/<record_id>/status")
@admin_required
def change_status(record_id):
    body = get_json_body()
    new_status = body.get("status")
    if new_status not in Status.ALL:
        return fail("无效的状态")
    insp = storage.find("inspections", record_id)
    if not insp:
        return fail("抽检记录不存在", 404)
    current = insp["status"]
    if new_status != Status.CLOSED and new_status not in Status.FLOW.get(current, []):
        return fail(f"状态不允许从 {Status.LABELS[current]} 变更为 {Status.LABELS[new_status]}")
    insp = storage.update("inspections", record_id, {"status": new_status})
    enrich_inspection(insp)
    return ok(insp, "状态已更新")
