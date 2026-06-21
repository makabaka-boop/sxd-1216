from datetime import datetime

from flask import Blueprint, g

from auth import login_required, role_required, team_lead_required
from constants import (
    RectificationStatus,
    RectificationTrigger,
    RectificationAcceptResult,
    Role,
)
from storage import storage, now_iso
from utils import ok, fail, get_json_body, parse_args, paginate
from inspection_common import enrich_rectification, manual_create_rectification, enrich_rectification_recurrence

bp = Blueprint("rectification", __name__, url_prefix="/api/rectifications")


def _filter_rectifications(items, args, user=None):
    if args.get("business_line_id"):
        items = [r for r in items if r.get("business_line_id") == args["business_line_id"]]
    if args.get("seat_group_id"):
        items = [r for r in items if r.get("seat_group_id") == args["seat_group_id"]]
    if args.get("inspection_id"):
        items = [r for r in items if r.get("inspection_id") == args["inspection_id"]]
    if args.get("status"):
        statuses = args["status"].split(",")
        items = [r for r in items if r.get("status") in statuses]
    if args.get("trigger_reason"):
        items = [r for r in items if r.get("trigger_reason") == args["trigger_reason"]]
    if args.get("assignee_id"):
        items = [r for r in items if r.get("assignee_id") == args["assignee_id"]]
    if args.get("responsible_user_id"):
        items = [r for r in items if r.get("responsible_user_id") == args["responsible_user_id"]]
    if args.get("initiator_id"):
        items = [r for r in items if r.get("initiator_id") == args["initiator_id"]]
    if args.get("overdue") in ("1", "true", "True"):
        now = now_iso()
        items = [
            r for r in items
            if r.get("plan_deadline") and r.get("plan_deadline") < now
            and r.get("status") not in (RectificationStatus.COMPLETED,)
        ]
    if args.get("start_date"):
        items = [r for r in items if r.get("created_at", "") >= args["start_date"]]
    if args.get("end_date"):
        items = [r for r in items if r.get("created_at", "") <= args["end_date"]]

    for r in items:
        enrich_rectification_recurrence(r)

    if args.get("is_recurrence") in ("1", "true", "True"):
        items = [r for r in items if r.get("is_recurrence")]
    elif args.get("is_recurrence") in ("0", "false", "False"):
        items = [r for r in items if not r.get("is_recurrence")]
    if args.get("recurrence_item_id"):
        target = args["recurrence_item_id"]
        items = [r for r in items if any(
            it.get("item_id") == target for it in (r.get("recurrence_items") or [])
        )]
    if args.get("recurrence_count_min") is not None and args.get("recurrence_count_min") != "":
        try:
            rc_min = int(args["recurrence_count_min"])
            items = [r for r in items if int(r.get("recurrence_count") or 0) >= rc_min]
        except ValueError:
            return fail("recurrence_count_min 必须为整数")

    if user and user["role"] == Role.TEAM_LEAD:
        items = [r for r in items if r.get("assignee_id") == user["id"]]
    return items


@bp.get("/statuses")
@login_required
def list_statuses():
    return ok([
        {"value": s, "label": RectificationStatus.LABELS[s]}
        for s in RectificationStatus.ALL
    ])


@bp.get("/triggers")
@login_required
def list_triggers():
    return ok([
        {"value": t, "label": RectificationTrigger.LABELS[t]}
        for t in RectificationTrigger.ALL
    ])


@bp.get("")
@login_required
def list_rectifications():
    args = parse_args()
    user = g.current_user
    items = storage.read("rectifications")
    items = _filter_rectifications(items, args, user)
    items.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    for r in items:
        enrich_rectification(r)
    return ok(paginate(items, args.get("page"), args.get("page_size")))


@bp.get("/mine")
@team_lead_required
def list_mine():
    args = parse_args()
    user = g.current_user
    items = storage.read("rectifications")
    items = [r for r in items if r.get("assignee_id") == user["id"]]
    items = _filter_rectifications(items, args)
    items.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    for r in items:
        enrich_rectification(r)
    return ok(paginate(items, args.get("page"), args.get("page_size")))


@bp.get("/summary")
@login_required
def rectification_summary():
    args = parse_args()
    user = g.current_user
    items = storage.read("rectifications")
    items = _filter_rectifications(items, args, user)
    for r in items:
        _sync_overdue(r)
    now = now_iso()
    summary = {
        "total": len(items),
        RectificationStatus.PENDING_RECTIFY: sum(
            1 for r in items if r.get("status") == RectificationStatus.PENDING_RECTIFY
        ),
        RectificationStatus.RECTIFYING: sum(
            1 for r in items if r.get("status") == RectificationStatus.RECTIFYING
        ),
        RectificationStatus.PENDING_ACCEPT: sum(
            1 for r in items if r.get("status") == RectificationStatus.PENDING_ACCEPT
        ),
        RectificationStatus.COMPLETED: sum(
            1 for r in items if r.get("status") == RectificationStatus.COMPLETED
        ),
        RectificationStatus.OVERDUE: sum(
            1 for r in items if r.get("status") == RectificationStatus.OVERDUE
        ),
        "overdue_count": sum(
            1 for r in items
            if r.get("plan_deadline") and r.get("plan_deadline") < now
            and r.get("status") not in (RectificationStatus.COMPLETED,)
        ),
    }
    completed = [r for r in items if r.get("status") == RectificationStatus.COMPLETED]
    summary["completion_rate"] = (
        round(len(completed) / len(items), 4) if items else 0.0
    )
    return ok(summary)


@bp.get("/<record_id>")
@login_required
def get_rectification(record_id):
    rect = storage.find("rectifications", record_id)
    if not rect:
        return fail("整改任务不存在", 404)
    user = g.current_user
    if user["role"] == Role.TEAM_LEAD and rect.get("assignee_id") != user["id"]:
        return fail("无权查看该整改任务", 403)
    enrich_rectification(rect)
    return ok(rect)


@bp.post("")
@role_required(Role.ADMIN, Role.INSPECTOR)
def create_rectification():
    body = get_json_body()
    inspection_id = body.get("inspection_id")
    if not inspection_id:
        return fail("inspection_id 不能为空")
    rect, err = manual_create_rectification(inspection_id, g.current_user["id"], body)
    if err:
        return fail(err)
    return ok(rect, "整改任务已创建")


@bp.post("/<record_id>/claim")
@team_lead_required
def claim_rectification(record_id):
    rect = storage.find("rectifications", record_id)
    if not rect:
        return fail("整改任务不存在", 404)
    if rect.get("assignee_id") and rect["assignee_id"] != g.current_user["id"]:
        return fail("该整改任务已分配给其他组长", 409)
    if rect.get("status") not in (RectificationStatus.PENDING_RECTIFY, RectificationStatus.OVERDUE):
        return fail(f"当前状态 {RectificationStatus.LABELS.get(rect['status'])} 不可领取")
    _sync_overdue(rect)
    patch = {
        "assignee_id": g.current_user["id"],
        "status": RectificationStatus.RECTIFYING,
    }
    rect = storage.update("rectifications", record_id, patch)
    enrich_rectification(rect)
    return ok(rect, "已领取整改任务")


@bp.put("/<record_id>/rectify")
@team_lead_required
def save_rectification(record_id):
    body = get_json_body()
    rect = storage.find("rectifications", record_id)
    if not rect:
        return fail("整改任务不存在", 404)
    if rect.get("assignee_id") != g.current_user["id"]:
        return fail("无权处理该整改任务", 403)
    if rect.get("status") not in (
        RectificationStatus.PENDING_RECTIFY,
        RectificationStatus.RECTIFYING,
        RectificationStatus.OVERDUE,
    ):
        return fail(f"当前状态 {RectificationStatus.LABELS.get(rect['status'])} 不可填写整改信息")
    patch = {}
    for k in ("rectify_measures", "responsible_user_id", "plan_deadline", "rectify_note", "attachment_link"):
        if k in body:
            patch[k] = body.get(k)
    if rect.get("status") in (RectificationStatus.PENDING_RECTIFY, RectificationStatus.OVERDUE):
        patch["status"] = RectificationStatus.RECTIFYING
    rect = storage.update("rectifications", record_id, patch)
    enrich_rectification(rect)
    return ok(rect, "整改信息已保存")


@bp.post("/<record_id>/submit")
@team_lead_required
def submit_rectification(record_id):
    body = get_json_body()
    rect = storage.find("rectifications", record_id)
    if not rect:
        return fail("整改任务不存在", 404)
    if rect.get("assignee_id") != g.current_user["id"]:
        return fail("无权处理该整改任务", 403)
    if rect.get("status") not in (RectificationStatus.RECTIFYING, RectificationStatus.OVERDUE):
        return fail(f"当前状态 {RectificationStatus.LABELS.get(rect['status'])} 不可提交")
    measures = (body.get("rectify_measures") or rect.get("rectify_measures") or "").strip()
    if not measures:
        return fail("整改措施不能为空")
    if not rect.get("responsible_user_id") and not body.get("responsible_user_id"):
        return fail("请指定整改责任人")
    patch = {}
    for k in ("rectify_measures", "responsible_user_id", "plan_deadline", "rectify_note", "attachment_link"):
        if k in body:
            patch[k] = body.get(k)
    patch["status"] = RectificationStatus.PENDING_ACCEPT
    patch["submitted_at"] = now_iso()
    rect = storage.update("rectifications", record_id, patch)
    enrich_rectification(rect)
    return ok(rect, "整改结果已提交，等待验收")


@bp.post("/<record_id>/remind")
@role_required(Role.ADMIN, Role.INSPECTOR)
def remind_rectification(record_id):
    body = get_json_body()
    rect = storage.find("rectifications", record_id)
    if not rect:
        return fail("整改任务不存在", 404)
    if rect.get("status") == RectificationStatus.COMPLETED:
        return fail("该整改任务已完成，无需催办")
    reminders = rect.get("reminders") or []
    reminders.append({
        "reminded_by": g.current_user["id"],
        "reminded_by_name": g.current_user.get("name"),
        "message": (body.get("message") or "").strip() or "请尽快处理整改任务",
        "reminded_at": now_iso(),
    })
    rect = storage.update("rectifications", record_id, {"reminders": reminders})
    enrich_rectification(rect)
    return ok(rect, "已发送催办提醒")


@bp.post("/<record_id>/accept")
@role_required(Role.ADMIN, Role.INSPECTOR)
def accept_rectification(record_id):
    body = get_json_body()
    rect = storage.find("rectifications", record_id)
    if not rect:
        return fail("整改任务不存在", 404)
    if rect.get("status") != RectificationStatus.PENDING_ACCEPT:
        return fail(f"当前状态 {RectificationStatus.LABELS.get(rect['status'])} 不可验收")
    result = body.get("result")
    if result not in RectificationAcceptResult.ALL:
        return fail("验收结果无效，可选 pass/reject")
    patch = {
        "acceptor_id": g.current_user["id"],
        "accept_result": result,
        "accept_note": body.get("accept_note"),
        "accepted_at": now_iso(),
    }
    if result == RectificationAcceptResult.PASS:
        patch["status"] = RectificationStatus.COMPLETED
    else:
        patch["status"] = RectificationStatus.RECTIFYING
        patch["reject_count"] = (rect.get("reject_count") or 0) + 1
    rect = storage.update("rectifications", record_id, patch)
    enrich_rectification(rect)
    msg = "验收通过" if result == RectificationAcceptResult.PASS else "已驳回，请重新整改"
    return ok(rect, msg)


@bp.put("/<record_id>/reassign")
@role_required(Role.ADMIN)
def reassign_rectification(record_id):
    body = get_json_body()
    rect = storage.find("rectifications", record_id)
    if not rect:
        return fail("整改任务不存在", 404)
    assignee_id = body.get("assignee_id")
    if not assignee_id:
        return fail("assignee_id 不能为空")
    assignee = storage.find("users", assignee_id)
    if not assignee:
        return fail("指定的处理人不存在")
    if assignee.get("role") not in (Role.TEAM_LEAD, Role.ADMIN):
        return fail("处理人角色必须为组长或管理员")
    rect = storage.update("rectifications", record_id, {"assignee_id": assignee_id})
    enrich_rectification(rect)
    return ok(rect, "整改任务已重新分配")


def _sync_overdue(rect):
    if rect.get("status") in (
        RectificationStatus.COMPLETED,
        RectificationStatus.PENDING_ACCEPT,
    ):
        return
    deadline = rect.get("plan_deadline")
    if not deadline:
        return
    if now_iso() > deadline and rect.get("status") != RectificationStatus.OVERDUE:
        storage.update("rectifications", rect["id"], {"status": RectificationStatus.OVERDUE})
        rect["status"] = RectificationStatus.OVERDUE
