from collections import defaultdict
from datetime import datetime

from flask import Blueprint

from auth import login_required
from constants import RectificationStatus
from storage import storage
from utils import ok, parse_args, name_of
from inspection_common import filter_inspections, enrich_inspection, enrich_appeal

bp = Blueprint("stats", __name__, url_prefix="/api/stats")


def _cfg():
    return storage.read("config") or {}


def _filter_rectifications(rectifications, args):
    items = list(rectifications)
    if args.get("business_line_id"):
        items = [r for r in items if r.get("business_line_id") == args["business_line_id"]]
    if args.get("seat_group_id"):
        items = [r for r in items if r.get("seat_group_id") == args["seat_group_id"]]
    if args.get("assignee_id"):
        items = [r for r in items if r.get("assignee_id") == args["assignee_id"]]
    if args.get("responsible_user_id"):
        items = [r for r in items if r.get("responsible_user_id") == args["responsible_user_id"]]
    if args.get("status"):
        statuses = args["status"].split(",")
        items = [r for r in items if r.get("status") in statuses]
    if args.get("start_date"):
        items = [r for r in items if r.get("created_at", "") >= args["start_date"]]
    if args.get("end_date"):
        items = [r for r in items if r.get("created_at", "") <= args["end_date"]]
    return items


def _duration_hours(start_str, end_str):
    if not start_str or not end_str:
        return None
    try:
        d1 = datetime.fromisoformat(start_str)
        d2 = datetime.fromisoformat(end_str)
        return round((d2 - d1).total_seconds() / 3600, 2)
    except Exception:
        return None


@bp.get("/deduction-ranking")
@login_required
def deduction_ranking():
    args = parse_args()
    inspections = filter_inspections(storage.read("inspections"), args)
    agg = defaultdict(lambda: {"count": 0, "total_deducted": 0.0})
    for insp in inspections:
        for d in insp.get("deductions") or []:
            key = d.get("item_id") or d.get("item_name") or "unknown"
            bucket = agg[key]
            bucket["item_id"] = key
            bucket["item_name"] = d.get("item_name") or key
            bucket["count"] += 1
            bucket["total_deducted"] += float(d.get("deducted", 0) or 0)
    rows = []
    for bucket in agg.values():
        rows.append({
            "item_id": bucket.get("item_id"),
            "item_name": bucket.get("item_name"),
            "count": bucket["count"],
            "total_deducted": round(bucket["total_deducted"], 2),
            "avg_deducted": round(bucket["total_deducted"] / bucket["count"], 2) if bucket["count"] else 0,
        })
    rows.sort(key=lambda r: r["total_deducted"], reverse=True)
    return ok({"items": rows, "total_inspections": len(inspections)})


@bp.get("/appeal-list")
@login_required
def appeal_list():
    args = parse_args()
    inspections = storage.read("inspections")
    insp_by_id = {i["id"]: i for i in inspections}
    items = storage.read("appeals")

    def _match(appeal):
        insp = insp_by_id.get(appeal.get("inspection_id"))
        if not insp:
            return False
        if args.get("business_line_id") and insp.get("business_line_id") != args["business_line_id"]:
            return False
        if args.get("seat_group_id") and insp.get("seat_group_id") != args["seat_group_id"]:
            return False
        if args.get("status") and insp.get("status") != args["status"]:
            return False
        if args.get("start_date") and appeal.get("created_at", "") < args["start_date"]:
            return False
        if args.get("end_date") and appeal.get("created_at", "") > args["end_date"]:
            return False
        return True

    items = [a for a in items if _match(a)]
    now = datetime.now().isoformat(timespec="seconds")
    for a in items:
        enrich_appeal(a)
        a["overdue"] = bool(a.get("deadline") and a.get("deadline") < now and not a.get("closed_at"))
    items.sort(key=lambda a: a.get("created_at", ""), reverse=True)
    summary = {
        "total": len(items),
        "overdue": sum(1 for a in items if a["overdue"]),
        "closed": sum(1 for a in items if a.get("closed_at")),
        "open": sum(1 for a in items if not a.get("closed_at")),
    }
    return ok({"items": items, "summary": summary})


@bp.get("/seat-group-trends")
@login_required
def seat_group_trends():
    args = parse_args()
    inspections = filter_inspections(storage.read("inspections"), args)
    inspections = [i for i in inspections if i.get("total_score") is not None]

    cfg = _cfg()
    low_threshold = cfg.get("low_score_threshold", 80)

    grouped = defaultdict(lambda: defaultdict(lambda: {"count": 0, "score_sum": 0.0, "low_count": 0}))
    for insp in inspections:
        sg = insp.get("seat_group_id") or "unknown"
        day = (insp.get("created_at") or "")[:10]
        bucket = grouped[sg][day]
        bucket["count"] += 1
        bucket["score_sum"] += float(insp["total_score"])
        if float(insp["total_score"]) < low_threshold:
            bucket["low_count"] += 1

    result = []
    for sg_id, days in grouped.items():
        trend = []
        for day in sorted(days.keys()):
            b = days[day]
            trend.append({
                "date": day,
                "count": b["count"],
                "avg_score": round(b["score_sum"] / b["count"], 2) if b["count"] else 0,
                "low_score_count": b["low_count"],
                "low_score_ratio": round(b["low_count"] / b["count"], 2) if b["count"] else 0,
            })
        result.append({
            "seat_group_id": sg_id,
            "seat_group_name": name_of("seat_groups", sg_id) if sg_id != "unknown" else None,
            "trend": trend,
            "total_count": sum(b["count"] for b in days.values()),
            "avg_score": round(sum(b["score_sum"] for b in days.values()) / max(sum(b["count"] for b in days.values()), 1), 2),
        })
    result.sort(key=lambda r: r["avg_score"])
    return ok({"items": result})


@bp.get("/rectification-overview")
@login_required
def rectification_overview():
    args = parse_args()
    rectifications = _filter_rectifications(storage.read("rectifications"), args)
    now = datetime.now().isoformat(timespec="seconds")

    total = len(rectifications)
    completed = sum(1 for r in rectifications if r.get("status") == RectificationStatus.COMPLETED)
    pending = sum(1 for r in rectifications if r.get("status") == RectificationStatus.PENDING_RECTIFY)
    rectifying = sum(1 for r in rectifications if r.get("status") == RectificationStatus.RECTIFYING)
    pending_accept = sum(1 for r in rectifications if r.get("status") == RectificationStatus.PENDING_ACCEPT)
    overdue_status = sum(1 for r in rectifications if r.get("status") == RectificationStatus.OVERDUE)
    overdue_count = sum(
        1 for r in rectifications
        if r.get("plan_deadline") and r.get("plan_deadline") < now
        and r.get("status") != RectificationStatus.COMPLETED
    )

    durations = []
    for r in rectifications:
        if r.get("status") == RectificationStatus.COMPLETED and r.get("submitted_at"):
            start = r.get("created_at")
            end = r.get("accepted_at") or r.get("submitted_at")
            d = _duration_hours(start, end)
            if d is not None:
                durations.append(d)

    avg_duration = round(sum(durations) / len(durations), 2) if durations else 0.0

    summary = {
        "total": total,
        "pending_rectify": pending,
        "rectifying": rectifying,
        "pending_accept": pending_accept,
        "completed": completed,
        "overdue_status": overdue_status,
        "overdue_count": overdue_count,
        "completion_rate": round(completed / total, 4) if total else 0.0,
        "avg_rectify_duration_hours": avg_duration,
        "total_reject_count": sum(int(r.get("reject_count") or 0) for r in rectifications),
    }
    return ok(summary)


@bp.get("/rectification-by-business-line")
@login_required
def rectification_by_business_line():
    args = parse_args()
    rectifications = _filter_rectifications(storage.read("rectifications"), args)
    now = datetime.now().isoformat(timespec="seconds")

    grouped = defaultdict(lambda: {
        "total": 0, "completed": 0, "pending_rectify": 0, "rectifying": 0,
        "pending_accept": 0, "overdue": 0, "durations": [],
    })
    for r in rectifications:
        bl_id = r.get("business_line_id") or "unknown"
        g = grouped[bl_id]
        g["total"] += 1
        status = r.get("status")
        if status == RectificationStatus.COMPLETED:
            g["completed"] += 1
        elif status == RectificationStatus.PENDING_RECTIFY:
            g["pending_rectify"] += 1
        elif status == RectificationStatus.RECTIFYING:
            g["rectifying"] += 1
        elif status == RectificationStatus.PENDING_ACCEPT:
            g["pending_accept"] += 1
        if (r.get("plan_deadline") and r.get("plan_deadline") < now
                and status != RectificationStatus.COMPLETED):
            g["overdue"] += 1
        if status == RectificationStatus.COMPLETED and r.get("submitted_at"):
            d = _duration_hours(r.get("created_at"), r.get("accepted_at") or r.get("submitted_at"))
            if d is not None:
                g["durations"].append(d)

    rows = []
    for bl_id, g in grouped.items():
        durations = g["durations"]
        avg_d = round(sum(durations) / len(durations), 2) if durations else 0.0
        rows.append({
            "business_line_id": bl_id if bl_id != "unknown" else None,
            "business_line_name": name_of("business_lines", bl_id) if bl_id != "unknown" else "未分配",
            "total": g["total"],
            "completed": g["completed"],
            "pending_rectify": g["pending_rectify"],
            "rectifying": g["rectifying"],
            "pending_accept": g["pending_accept"],
            "overdue": g["overdue"],
            "completion_rate": round(g["completed"] / g["total"], 4) if g["total"] else 0.0,
            "avg_rectify_duration_hours": avg_d,
        })
    rows.sort(key=lambda r: r["completion_rate"])
    return ok({"items": rows, "total_groups": len(rows)})


@bp.get("/rectification-by-seat-group")
@login_required
def rectification_by_seat_group():
    args = parse_args()
    rectifications = _filter_rectifications(storage.read("rectifications"), args)
    now = datetime.now().isoformat(timespec="seconds")

    grouped = defaultdict(lambda: {
        "total": 0, "completed": 0, "pending_rectify": 0, "rectifying": 0,
        "pending_accept": 0, "overdue": 0, "durations": [],
    })
    for r in rectifications:
        sg_id = r.get("seat_group_id") or "unknown"
        g = grouped[sg_id]
        g["total"] += 1
        status = r.get("status")
        if status == RectificationStatus.COMPLETED:
            g["completed"] += 1
        elif status == RectificationStatus.PENDING_RECTIFY:
            g["pending_rectify"] += 1
        elif status == RectificationStatus.RECTIFYING:
            g["rectifying"] += 1
        elif status == RectificationStatus.PENDING_ACCEPT:
            g["pending_accept"] += 1
        if (r.get("plan_deadline") and r.get("plan_deadline") < now
                and status != RectificationStatus.COMPLETED):
            g["overdue"] += 1
        if status == RectificationStatus.COMPLETED and r.get("submitted_at"):
            d = _duration_hours(r.get("created_at"), r.get("accepted_at") or r.get("submitted_at"))
            if d is not None:
                g["durations"].append(d)

    rows = []
    for sg_id, g in grouped.items():
        durations = g["durations"]
        avg_d = round(sum(durations) / len(durations), 2) if durations else 0.0
        rows.append({
            "seat_group_id": sg_id if sg_id != "unknown" else None,
            "seat_group_name": name_of("seat_groups", sg_id) if sg_id != "unknown" else "未分配",
            "business_line_id": None,
            "business_line_name": None,
            "total": g["total"],
            "completed": g["completed"],
            "pending_rectify": g["pending_rectify"],
            "rectifying": g["rectifying"],
            "pending_accept": g["pending_accept"],
            "overdue": g["overdue"],
            "completion_rate": round(g["completed"] / g["total"], 4) if g["total"] else 0.0,
            "avg_rectify_duration_hours": avg_d,
        })
    for row in rows:
        sg = storage.find("seat_groups", row["seat_group_id"]) if row["seat_group_id"] else None
        if sg:
            row["business_line_id"] = sg.get("business_line_id")
            row["business_line_name"] = name_of("business_lines", sg.get("business_line_id"))
    rows.sort(key=lambda r: r["completion_rate"])
    return ok({"items": rows, "total_groups": len(rows)})


@bp.get("/rectification-by-responsible")
@login_required
def rectification_by_responsible():
    args = parse_args()
    rectifications = _filter_rectifications(storage.read("rectifications"), args)
    now = datetime.now().isoformat(timespec="seconds")

    grouped = defaultdict(lambda: {
        "total": 0, "completed": 0, "pending_rectify": 0, "rectifying": 0,
        "pending_accept": 0, "overdue": 0, "durations": [],
    })
    for r in rectifications:
        user_id = r.get("responsible_user_id") or r.get("assignee_id") or "unknown"
        g = grouped[user_id]
        g["total"] += 1
        status = r.get("status")
        if status == RectificationStatus.COMPLETED:
            g["completed"] += 1
        elif status == RectificationStatus.PENDING_RECTIFY:
            g["pending_rectify"] += 1
        elif status == RectificationStatus.RECTIFYING:
            g["rectifying"] += 1
        elif status == RectificationStatus.PENDING_ACCEPT:
            g["pending_accept"] += 1
        if (r.get("plan_deadline") and r.get("plan_deadline") < now
                and status != RectificationStatus.COMPLETED):
            g["overdue"] += 1
        if status == RectificationStatus.COMPLETED and r.get("submitted_at"):
            d = _duration_hours(r.get("created_at"), r.get("accepted_at") or r.get("submitted_at"))
            if d is not None:
                g["durations"].append(d)

    rows = []
    for user_id, g in grouped.items():
        durations = g["durations"]
        avg_d = round(sum(durations) / len(durations), 2) if durations else 0.0
        user = storage.find("users", user_id) if user_id != "unknown" else None
        seat_group_id = user.get("seat_group_id") if user else None
        rows.append({
            "responsible_user_id": user_id if user_id != "unknown" else None,
            "responsible_user_name": user.get("name") if user else "未指定",
            "role": user.get("role") if user else None,
            "seat_group_id": seat_group_id,
            "seat_group_name": name_of("seat_groups", seat_group_id),
            "business_line_id": user.get("business_line_id") if user else None,
            "business_line_name": name_of("business_lines", user.get("business_line_id")) if user else None,
            "total": g["total"],
            "completed": g["completed"],
            "pending_rectify": g["pending_rectify"],
            "rectifying": g["rectifying"],
            "pending_accept": g["pending_accept"],
            "overdue": g["overdue"],
            "completion_rate": round(g["completed"] / g["total"], 4) if g["total"] else 0.0,
            "avg_rectify_duration_hours": avg_d,
        })
    rows.sort(key=lambda r: r["completion_rate"])
    return ok({"items": rows, "total_users": len(rows)})


@bp.get("/rectification-list")
@login_required
def rectification_list():
    args = parse_args()
    items = _filter_rectifications(storage.read("rectifications"), args)
    items.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    from inspection_common import enrich_rectification
    for r in items:
        enrich_rectification(r)
    return ok({"items": items, "total": len(items)})


@bp.get("/recurrence-overview")
@login_required
def recurrence_overview():
    args = parse_args()
    from inspection_common import detect_inspection_recurrence
    inspections = filter_inspections(storage.read("inspections"), args)
    total = len(inspections)
    recurrence_count = 0
    total_recurrence_times = 0
    item_recurrence = defaultdict(lambda: {
        "item_id": None, "item_name": None, "count": 0, "deducted_sum": 0.0
    })
    for insp in inspections:
        info = detect_inspection_recurrence(insp)
        if info["is_recurrence"]:
            recurrence_count += 1
            total_recurrence_times += info["recurrence_count"]
            for it in info.get("recurrence_items") or []:
                key = it.get("item_id") or "unknown"
                b = item_recurrence[key]
                b["item_id"] = key
                b["item_name"] = it.get("item_name") or b["item_name"]
                b["count"] += 1
                b["deducted_sum"] += float(it.get("deducted_b", 0) or 0)
    top_items = sorted(item_recurrence.values(), key=lambda x: x["count"], reverse=True)[:10]
    for it in top_items:
        it["deducted_sum"] = round(it["deducted_sum"], 2)
    return ok({
        "total_inspections": total,
        "recurrence_count": recurrence_count,
        "recurrence_ratio": round(recurrence_count / max(total, 1), 4),
        "avg_recurrence_times": round(total_recurrence_times / max(recurrence_count, 1), 2) if recurrence_count else 0,
        "top_recurrence_items": top_items,
    })


@bp.get("/recurrence-by-business-line")
@login_required
def recurrence_by_business_line():
    args = parse_args()
    from inspection_common import detect_inspection_recurrence
    inspections = filter_inspections(storage.read("inspections"), args)
    grouped = defaultdict(lambda: {
        "business_line_id": None,
        "business_line_name": None,
        "total_inspections": 0,
        "recurrence_count": 0,
        "total_recurrence_times": 0,
        "items": defaultdict(lambda: {"item_id": None, "item_name": None, "count": 0}),
    })
    for insp in inspections:
        bl_id = insp.get("business_line_id") or "unknown"
        g = grouped[bl_id]
        g["business_line_id"] = bl_id if bl_id != "unknown" else None
        g["business_line_name"] = name_of("business_lines", bl_id) if bl_id != "unknown" else "未分配"
        g["total_inspections"] += 1
        info = detect_inspection_recurrence(insp)
        if info["is_recurrence"]:
            g["recurrence_count"] += 1
            g["total_recurrence_times"] += info["recurrence_count"]
            for it in info.get("recurrence_items") or []:
                key = it.get("item_id") or "unknown"
                ib = g["items"][key]
                ib["item_id"] = key
                ib["item_name"] = it.get("item_name") or ib["item_name"]
                ib["count"] += 1
    rows = []
    for bl_id, g in grouped.items():
        top_items = sorted(g["items"].values(), key=lambda x: x["count"], reverse=True)[:5]
        rows.append({
            "business_line_id": g["business_line_id"],
            "business_line_name": g["business_line_name"],
            "total_inspections": g["total_inspections"],
            "recurrence_count": g["recurrence_count"],
            "recurrence_ratio": round(g["recurrence_count"] / max(g["total_inspections"], 1), 4),
            "avg_recurrence_times": round(g["total_recurrence_times"] / max(g["recurrence_count"], 1), 2) if g["recurrence_count"] else 0,
            "top_recurrence_items": top_items,
        })
    rows.sort(key=lambda r: r["recurrence_ratio"], reverse=True)
    return ok({"items": rows, "total_groups": len(rows)})


@bp.get("/recurrence-by-seat-group")
@login_required
def recurrence_by_seat_group():
    args = parse_args()
    from inspection_common import detect_inspection_recurrence
    inspections = filter_inspections(storage.read("inspections"), args)
    grouped = defaultdict(lambda: {
        "seat_group_id": None,
        "seat_group_name": None,
        "business_line_id": None,
        "business_line_name": None,
        "total_inspections": 0,
        "recurrence_count": 0,
        "total_recurrence_times": 0,
        "items": defaultdict(lambda: {"item_id": None, "item_name": None, "count": 0}),
    })
    for insp in inspections:
        sg_id = insp.get("seat_group_id") or "unknown"
        g = grouped[sg_id]
        g["seat_group_id"] = sg_id if sg_id != "unknown" else None
        g["seat_group_name"] = name_of("seat_groups", sg_id) if sg_id != "unknown" else "未分配"
        g["business_line_id"] = insp.get("business_line_id")
        g["business_line_name"] = name_of("business_lines", insp.get("business_line_id"))
        g["total_inspections"] += 1
        info = detect_inspection_recurrence(insp)
        if info["is_recurrence"]:
            g["recurrence_count"] += 1
            g["total_recurrence_times"] += info["recurrence_count"]
            for it in info.get("recurrence_items") or []:
                key = it.get("item_id") or "unknown"
                ib = g["items"][key]
                ib["item_id"] = key
                ib["item_name"] = it.get("item_name") or ib["item_name"]
                ib["count"] += 1
    rows = []
    for sg_id, g in grouped.items():
        top_items = sorted(g["items"].values(), key=lambda x: x["count"], reverse=True)[:5]
        rows.append({
            "seat_group_id": g["seat_group_id"],
            "seat_group_name": g["seat_group_name"],
            "business_line_id": g["business_line_id"],
            "business_line_name": g["business_line_name"],
            "total_inspections": g["total_inspections"],
            "recurrence_count": g["recurrence_count"],
            "recurrence_ratio": round(g["recurrence_count"] / max(g["total_inspections"], 1), 4),
            "avg_recurrence_times": round(g["total_recurrence_times"] / max(g["recurrence_count"], 1), 2) if g["recurrence_count"] else 0,
            "top_recurrence_items": top_items,
        })
    rows.sort(key=lambda r: r["recurrence_ratio"], reverse=True)
    return ok({"items": rows, "total_groups": len(rows)})


@bp.get("/recurrence-by-item")
@login_required
def recurrence_by_item():
    args = parse_args()
    from inspection_common import detect_inspection_recurrence
    inspections = filter_inspections(storage.read("inspections"), args)
    grouped = defaultdict(lambda: {
        "item_id": None,
        "item_name": None,
        "recurrence_count": 0,
        "affected_seat_groups": set(),
        "affected_inspections": set(),
        "deducted_sum": 0.0,
    })
    for insp in inspections:
        info = detect_inspection_recurrence(insp)
        if not info["is_recurrence"]:
            continue
        sg_id = insp.get("seat_group_id") or "unknown"
        for it in info.get("recurrence_items") or []:
            key = it.get("item_id") or "unknown"
            g = grouped[key]
            g["item_id"] = key
            g["item_name"] = it.get("item_name") or g["item_name"]
            g["recurrence_count"] += 1
            g["affected_seat_groups"].add(sg_id)
            g["affected_inspections"].add(insp.get("id"))
            g["deducted_sum"] += float(it.get("deducted_b", 0) or 0)
    rows = []
    for item_id, g in grouped.items():
        rows.append({
            "item_id": g["item_id"],
            "item_name": g["item_name"],
            "recurrence_count": g["recurrence_count"],
            "affected_seat_group_count": len(g["affected_seat_groups"]),
            "affected_inspection_count": len(g["affected_inspections"]),
            "total_deducted": round(g["deducted_sum"], 2),
        })
    rows.sort(key=lambda r: r["recurrence_count"], reverse=True)
    return ok({"items": rows, "total_items": len(rows)})


@bp.get("/recurrence-trend")
@login_required
def recurrence_trend():
    args = parse_args()
    from inspection_common import detect_inspection_recurrence
    inspections = filter_inspections(storage.read("inspections"), args)
    grouped = defaultdict(lambda: {
        "date": None,
        "total_inspections": 0,
        "recurrence_count": 0,
        "items": defaultdict(lambda: {"item_id": None, "item_name": None, "count": 0}),
    })
    for insp in inspections:
        day = (insp.get("created_at") or "")[:10]
        if not day:
            continue
        g = grouped[day]
        g["date"] = day
        g["total_inspections"] += 1
        info = detect_inspection_recurrence(insp)
        if info["is_recurrence"]:
            g["recurrence_count"] += 1
            for it in info.get("recurrence_items") or []:
                key = it.get("item_id") or "unknown"
                ib = g["items"][key]
                ib["item_id"] = key
                ib["item_name"] = it.get("item_name") or ib["item_name"]
                ib["count"] += 1
    trend = []
    for day in sorted(grouped.keys()):
        g = grouped[day]
        top_items = sorted(g["items"].values(), key=lambda x: x["count"], reverse=True)[:3]
        trend.append({
            "date": g["date"],
            "total_inspections": g["total_inspections"],
            "recurrence_count": g["recurrence_count"],
            "recurrence_ratio": round(g["recurrence_count"] / max(g["total_inspections"], 1), 4),
            "top_items": top_items,
        })
    return ok({"trend": trend, "total_days": len(trend)})
