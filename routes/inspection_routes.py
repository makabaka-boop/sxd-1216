from flask import Blueprint, g

from auth import login_required, admin_required
from constants import Status
from storage import storage
from utils import ok, fail, parse_args, paginate, get_json_body
from inspection_common import enrich_inspection, auto_create_rectification, enrich_inspection_recurrence

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

    for i in items:
        enrich_inspection_recurrence(i)

    if args.get("is_recurrence") in ("1", "true", "True"):
        items = [i for i in items if i.get("is_recurrence")]
    elif args.get("is_recurrence") in ("0", "false", "False"):
        items = [i for i in items if not i.get("is_recurrence")]
    if args.get("recurrence_item_id"):
        target = args["recurrence_item_id"]
        items = [i for i in items if any(
            it.get("item_id") == target for it in (i.get("recurrence_items") or [])
        )]
    if args.get("recurrence_count_min") is not None and args.get("recurrence_count_min") != "":
        try:
            rc_min = int(args["recurrence_count_min"])
            items = [i for i in items if int(i.get("recurrence_count") or 0) >= rc_min]
        except ValueError:
            return fail("recurrence_count_min 必须为整数")

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
    data = {}
    if new_status == Status.CLOSED:
        insp = storage.find("inspections", record_id)
        rect = auto_create_rectification(insp, g.current_user["id"], context="close")
        if rect:
            data["rectification"] = rect
    enrich_inspection(insp)
    data["inspection"] = insp
    return ok(data, "状态已更新")
