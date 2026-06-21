from collections import defaultdict
from datetime import datetime

from flask import Blueprint

from auth import login_required
from constants import Status, RectificationStatus, RectificationTrigger
from storage import storage
from utils import ok, parse_args, name_of
from inspection_common import filter_inspections, enrich_rectification, detect_inspection_recurrence

bp = Blueprint("risk", __name__, url_prefix="/api/risk")


def _cfg():
    return storage.read("config") or {}


@bp.get("/alerts")
@login_required
def alerts():
    args = parse_args()
    cfg = _cfg()
    low_threshold = float(cfg.get("low_score_threshold", 80))
    risk_ratio = float(cfg.get("risk_low_score_ratio", 0.3))
    min_sample = int(cfg.get("risk_min_sample", 3))
    frequent_threshold = int(cfg.get("frequent_item_threshold", 3))
    repeat_threshold = int(cfg.get("repeat_rectify_threshold", 2))
    recurrence_alert_threshold = int(cfg.get("recurrence_alert_threshold", 2))

    inspections = filter_inspections(storage.read("inspections"), args)
    scored = [i for i in inspections if i.get("total_score") is not None]
    now = datetime.now().isoformat(timespec="seconds")

    low_score_concentration = _low_score_concentration(scored, low_threshold, risk_ratio, min_sample)
    overdue_appeals = _overdue_appeals(args, now)
    frequent_items = _frequent_items(scored, frequent_threshold)
    missing_reviews = _missing_reviews(args)
    rising_risks = _rising_seat_group_risk(scored, low_threshold, risk_ratio, min_sample)
    overdue_rectifications = _overdue_rectifications(args, now)
    repeat_rectify_issues = _repeat_rectify_issues(args, repeat_threshold)
    recurrence_alerts = _recurrence_alerts(args, recurrence_alert_threshold)

    summary = {
        "low_score_concentration": len(low_score_concentration),
        "overdue_appeals": len(overdue_appeals),
        "frequent_item_issues": len(frequent_items),
        "missing_review_conclusions": len(missing_reviews),
        "rising_seat_group_risk": len(rising_risks),
        "overdue_rectifications": len(overdue_rectifications),
        "repeat_rectify_issues": len(repeat_rectify_issues),
        "recurrence_alerts": len(recurrence_alerts),
        "total_alerts": (len(low_score_concentration) + len(overdue_appeals)
                         + len(frequent_items) + len(missing_reviews) + len(rising_risks)
                         + len(overdue_rectifications) + len(repeat_rectify_issues)
                         + len(recurrence_alerts)),
    }
    return ok({"summary": summary, "alerts": {
        "low_score_concentration": low_score_concentration,
        "overdue_appeals": overdue_appeals,
        "frequent_item_issues": frequent_items,
        "missing_review_conclusions": missing_reviews,
        "rising_seat_group_risk": rising_risks,
        "overdue_rectifications": overdue_rectifications,
        "repeat_rectify_issues": repeat_rectify_issues,
        "recurrence_alerts": recurrence_alerts,
    }})


def _low_score_concentration(scored, low_threshold, risk_ratio, min_sample):
    groups = defaultdict(list)
    for insp in scored:
        groups[insp.get("seat_group_id") or "unknown"].append(insp)
    result = []
    for sg_id, items in groups.items():
        if len(items) < min_sample:
            continue
        low = [i for i in items if float(i["total_score"]) < low_threshold]
        ratio = len(low) / len(items)
        if ratio >= risk_ratio:
            result.append({
                "seat_group_id": sg_id,
                "seat_group_name": name_of("seat_groups", sg_id) if sg_id != "unknown" else None,
                "total": len(items),
                "low_score_count": len(low),
                "low_score_ratio": round(ratio, 2),
                "threshold": risk_ratio,
                "avg_score": round(sum(float(i["total_score"]) for i in items) / len(items), 2),
            })
    result.sort(key=lambda r: r["low_score_ratio"], reverse=True)
    return result


def _overdue_appeals(args, now):
    appeals = storage.read("appeals")
    insp_by_id = {i["id"]: i for i in storage.read("inspections")}
    result = []
    for a in appeals:
        if not a.get("deadline") or a.get("closed_at"):
            continue
        if a.get("deadline") >= now:
            continue
        insp = insp_by_id.get(a.get("inspection_id"))
        if not insp:
            continue
        if args.get("business_line_id") and insp.get("business_line_id") != args["business_line_id"]:
            continue
        if args.get("seat_group_id") and insp.get("seat_group_id") != args["seat_group_id"]:
            continue
        result.append({
            "appeal_id": a["id"],
            "inspection_id": a["inspection_id"],
            "call_id": insp.get("call_id"),
            "seat_group_id": insp.get("seat_group_id"),
            "seat_group_name": name_of("seat_groups", insp.get("seat_group_id")),
            "deadline": a.get("deadline"),
            "created_at": a.get("created_at"),
            "status": insp.get("status"),
        })
    return result


def _overdue_rectifications(args, now):
    rectifications = storage.read("rectifications")
    result = []
    for r in rectifications:
        if r.get("status") == RectificationStatus.COMPLETED:
            continue
        deadline = r.get("plan_deadline")
        if not deadline or deadline >= now:
            continue
        if args.get("business_line_id") and r.get("business_line_id") != args["business_line_id"]:
            continue
        if args.get("seat_group_id") and r.get("seat_group_id") != args["seat_group_id"]:
            continue
        insp = storage.find("inspections", r.get("inspection_id"))
        overdue_hours = 0
        try:
            d1 = datetime.fromisoformat(now)
            d2 = datetime.fromisoformat(deadline)
            overdue_hours = round((d1 - d2).total_seconds() / 3600, 1)
        except Exception:
            pass
        result.append({
            "rectification_id": r["id"],
            "inspection_id": r.get("inspection_id"),
            "call_id": insp.get("call_id") if insp else None,
            "title": r.get("title"),
            "seat_group_id": r.get("seat_group_id"),
            "seat_group_name": name_of("seat_groups", r.get("seat_group_id")),
            "assignee_id": r.get("assignee_id"),
            "assignee_name": name_of("users", r.get("assignee_id"), "name"),
            "trigger_reason": r.get("trigger_reason"),
            "trigger_label": RectificationTrigger.LABELS.get(r.get("trigger_reason"), r.get("trigger_reason")),
            "status": r.get("status"),
            "status_label": RectificationStatus.LABELS.get(r.get("status"), r.get("status")),
            "plan_deadline": deadline,
            "created_at": r.get("created_at"),
            "overdue_hours": overdue_hours,
        })
    result.sort(key=lambda x: x["overdue_hours"], reverse=True)
    return result


def _repeat_rectify_issues(args, threshold):
    rectifications = storage.read("rectifications")
    if args.get("business_line_id"):
        rectifications = [r for r in rectifications if r.get("business_line_id") == args["business_line_id"]]
    if args.get("seat_group_id"):
        rectifications = [r for r in rectifications if r.get("seat_group_id") == args["seat_group_id"]]

    item_rect_map = defaultdict(lambda: {"count": 0, "rect_ids": [], "inspection_ids": set()})

    for r in rectifications:
        insp = storage.find("inspections", r.get("inspection_id"))
        if not insp:
            continue
        deductions = insp.get("deductions") or []
        for d in deductions:
            key = d.get("item_id") or d.get("item_name") or "unknown"
            bucket = item_rect_map[key]
            bucket["item_name"] = d.get("item_name") or key
            bucket["max_deducted"] = max(
                bucket.get("max_deducted", 0),
                float(d.get("deducted", 0) or 0)
            )
            bucket["count"] += 1
            bucket["rect_ids"].append(r["id"])
            bucket["inspection_ids"].add(insp["id"])

    result = []
    for key, bucket in item_rect_map.items():
        if bucket["count"] < threshold:
            continue
        last_rect = None
        if bucket["rect_ids"]:
            last_rect_id = bucket["rect_ids"][-1]
            last_rect = storage.find("rectifications", last_rect_id)
        result.append({
            "item_id": key,
            "item_name": bucket["item_name"],
            "rectification_count": bucket["count"],
            "affected_inspections": len(bucket["inspection_ids"]),
            "max_deducted": round(bucket.get("max_deducted", 0), 2),
            "threshold": threshold,
            "last_rectification_id": last_rect.get("id") if last_rect else None,
            "last_rectification_status": last_rect.get("status") if last_rect else None,
            "last_rectification_status_label": RectificationStatus.LABELS.get(last_rect.get("status"), last_rect.get("status")) if last_rect else None,
            "last_rectification_at": last_rect.get("created_at") if last_rect else None,
        })
    result.sort(key=lambda r: r["rectification_count"], reverse=True)
    return result


def _frequent_items(scored, threshold):
    agg = defaultdict(lambda: {"count": 0, "inspections": set()})
    for insp in scored:
        for d in insp.get("deductions") or []:
            key = d.get("item_id") or d.get("item_name") or "unknown"
            bucket = agg[key]
            bucket["item_name"] = d.get("item_name") or key
            bucket["count"] += 1
            bucket["inspections"].add(insp["id"])
    result = []
    for key, bucket in agg.items():
        if bucket["count"] >= threshold:
            result.append({
                "item_id": key,
                "item_name": bucket["item_name"],
                "occurrences": bucket["count"],
                "affected_inspections": len(bucket["inspections"]),
                "threshold": threshold,
            })
    result.sort(key=lambda r: r["occurrences"], reverse=True)
    return result


def _missing_reviews(args):
    inspections = filter_inspections(storage.read("inspections"), args)
    reviews = storage.read("reviews")
    reviewed_ids = {r.get("inspection_id") for r in reviews}
    result = []
    for insp in inspections:
        if insp.get("status") == Status.PENDING_REVIEW and insp["id"] not in reviewed_ids:
            result.append({
                "inspection_id": insp["id"],
                "call_id": insp.get("call_id"),
                "seat_group_id": insp.get("seat_group_id"),
                "seat_group_name": name_of("seat_groups", insp.get("seat_group_id")),
                "status": insp.get("status"),
                "submitted_at": insp.get("submitted_at"),
            })
    return result


def _rising_seat_group_risk(scored, low_threshold, risk_ratio, min_sample):
    grouped = defaultdict(lambda: defaultdict(lambda: {"count": 0, "score_sum": 0.0, "low_count": 0}))
    for insp in scored:
        sg = insp.get("seat_group_id") or "unknown"
        day = (insp.get("created_at") or "")[:10]
        b = grouped[sg][day]
        b["count"] += 1
        b["score_sum"] += float(insp["total_score"])
        if float(insp["total_score"]) < low_threshold:
            b["low_count"] += 1

    result = []
    for sg_id, days in grouped.items():
        ordered = sorted(days.keys())
        if len(ordered) < 2:
            continue
        prev = days[ordered[-2]]
        curr = days[ordered[-1]]
        if curr["count"] < min_sample or prev["count"] < 1:
            continue
        prev_avg = prev["score_sum"] / prev["count"]
        curr_avg = curr["score_sum"] / curr["count"] if curr["count"] else 0
        prev_low_ratio = prev["low_count"] / prev["count"]
        curr_low_ratio = curr["low_count"] / curr["count"] if curr["count"] else 0
        declining = curr_avg < prev_avg
        low_rising = curr_low_ratio > prev_low_ratio
        if declining or low_rising or curr_low_ratio >= risk_ratio:
            result.append({
                "seat_group_id": sg_id,
                "seat_group_name": name_of("seat_groups", sg_id) if sg_id != "unknown" else None,
                "latest_date": ordered[-1],
                "prev_avg_score": round(prev_avg, 2),
                "curr_avg_score": round(curr_avg, 2),
                "prev_low_ratio": round(prev_low_ratio, 2),
                "curr_low_ratio": round(curr_low_ratio, 2),
                "declining": declining,
                "low_rising": low_rising,
            })
    result.sort(key=lambda r: r["curr_avg_score"])
    return result


def _recurrence_alerts(args, threshold):
    inspections = filter_inspections(storage.read("inspections"), args)
    seat_group_stats = defaultdict(lambda: {
        "seat_group_id": None,
        "seat_group_name": None,
        "business_line_id": None,
        "business_line_name": None,
        "recurrence_count": 0,
        "total_inspections": 0,
        "recurrence_items": defaultdict(lambda: {"count": 0, "item_name": None, "deducted_sum": 0.0}),
        "latest_recurrence_at": None,
        "inspections": [],
    })
    item_stats = defaultdict(lambda: {
        "item_id": None,
        "item_name": None,
        "recurrence_count": 0,
        "seat_groups": set(),
        "affected_inspections": set(),
        "deducted_sum": 0.0,
        "latest_recurrence_at": None,
    })
    business_line_stats = defaultdict(lambda: {
        "business_line_id": None,
        "business_line_name": None,
        "recurrence_count": 0,
        "total_inspections": 0,
        "recurrence_items": defaultdict(lambda: {"count": 0, "item_name": None}),
        "latest_recurrence_at": None,
    })

    for insp in inspections:
        info = detect_inspection_recurrence(insp)
        sg_id = insp.get("seat_group_id") or "unknown"
        bl_id = insp.get("business_line_id") or "unknown"
        sg_bucket = seat_group_stats[sg_id]
        sg_bucket["seat_group_id"] = sg_id if sg_id != "unknown" else None
        sg_bucket["seat_group_name"] = name_of("seat_groups", sg_id) if sg_id != "unknown" else "未分配"
        sg_bucket["business_line_id"] = insp.get("business_line_id")
        sg_bucket["business_line_name"] = name_of("business_lines", insp.get("business_line_id"))
        sg_bucket["total_inspections"] += 1

        bl_bucket = business_line_stats[bl_id]
        bl_bucket["business_line_id"] = bl_id if bl_id != "unknown" else None
        bl_bucket["business_line_name"] = name_of("business_lines", bl_id) if bl_id != "unknown" else "未分配"
        bl_bucket["total_inspections"] += 1

        if info["is_recurrence"]:
            sg_bucket["recurrence_count"] += 1
            bl_bucket["recurrence_count"] += 1
            created = insp.get("created_at")
            if created and (not sg_bucket["latest_recurrence_at"] or created > sg_bucket["latest_recurrence_at"]):
                sg_bucket["latest_recurrence_at"] = created
            if created and (not bl_bucket["latest_recurrence_at"] or created > bl_bucket["latest_recurrence_at"]):
                bl_bucket["latest_recurrence_at"] = created
            sg_bucket["inspections"].append({
                "inspection_id": insp.get("id"),
                "call_id": insp.get("call_id"),
                "created_at": created,
                "recurrence_count": info["recurrence_count"],
            })
            for it in info.get("recurrence_items") or []:
                item_id = it.get("item_id") or "unknown"
                sg_item = sg_bucket["recurrence_items"][item_id]
                sg_item["item_id"] = item_id
                sg_item["item_name"] = it.get("item_name") or sg_item["item_name"]
                sg_item["count"] += 1

                bl_item = bl_bucket["recurrence_items"][item_id]
                bl_item["item_id"] = item_id
                bl_item["item_name"] = it.get("item_name") or bl_item["item_name"]
                bl_item["count"] += 1

                it_bucket = item_stats[item_id]
                it_bucket["item_id"] = item_id
                it_bucket["item_name"] = it.get("item_name") or it_bucket["item_name"]
                it_bucket["recurrence_count"] += 1
                it_bucket["seat_groups"].add(sg_id)
                it_bucket["affected_inspections"].add(insp.get("id"))
                it_bucket["deducted_sum"] += float(it.get("deducted_b", 0) or 0)
                if created and (not it_bucket["latest_recurrence_at"] or created > it_bucket["latest_recurrence_at"]):
                    it_bucket["latest_recurrence_at"] = created

    seat_group_alerts = []
    for sg_id, bucket in seat_group_stats.items():
        if bucket["recurrence_count"] < threshold:
            continue
        top_items = sorted(
            bucket["recurrence_items"].values(),
            key=lambda x: x["count"], reverse=True
        )[:5]
        seat_group_alerts.append({
            "seat_group_id": bucket["seat_group_id"],
            "seat_group_name": bucket["seat_group_name"],
            "business_line_id": bucket["business_line_id"],
            "business_line_name": bucket["business_line_name"],
            "recurrence_count": bucket["recurrence_count"],
            "total_inspections": bucket["total_inspections"],
            "recurrence_ratio": round(bucket["recurrence_count"] / max(bucket["total_inspections"], 1), 4),
            "threshold": threshold,
            "top_items": top_items,
            "latest_recurrence_at": bucket["latest_recurrence_at"],
        })
    seat_group_alerts.sort(key=lambda x: x["recurrence_count"], reverse=True)

    item_alerts = []
    for item_id, bucket in item_stats.items():
        if bucket["recurrence_count"] < threshold:
            continue
        item_alerts.append({
            "item_id": bucket["item_id"],
            "item_name": bucket["item_name"],
            "recurrence_count": bucket["recurrence_count"],
            "affected_seat_group_count": len(bucket["seat_groups"]),
            "affected_inspection_count": len(bucket["affected_inspections"]),
            "total_deducted": round(bucket["deducted_sum"], 2),
            "threshold": threshold,
            "latest_recurrence_at": bucket["latest_recurrence_at"],
        })
    item_alerts.sort(key=lambda x: x["recurrence_count"], reverse=True)

    business_line_alerts = []
    for bl_id, bucket in business_line_stats.items():
        if bucket["recurrence_count"] < threshold:
            continue
        top_items = sorted(
            bucket["recurrence_items"].values(),
            key=lambda x: x["count"], reverse=True
        )[:5]
        business_line_alerts.append({
            "business_line_id": bucket["business_line_id"],
            "business_line_name": bucket["business_line_name"],
            "recurrence_count": bucket["recurrence_count"],
            "total_inspections": bucket["total_inspections"],
            "recurrence_ratio": round(bucket["recurrence_count"] / max(bucket["total_inspections"], 1), 4),
            "threshold": threshold,
            "top_items": top_items,
            "latest_recurrence_at": bucket["latest_recurrence_at"],
        })
    business_line_alerts.sort(key=lambda x: x["recurrence_count"], reverse=True)

    return {
        "by_seat_group": seat_group_alerts,
        "by_item": item_alerts,
        "by_business_line": business_line_alerts,
        "total_seat_group_alerts": len(seat_group_alerts),
        "total_item_alerts": len(item_alerts),
        "total_business_line_alerts": len(business_line_alerts),
    }
