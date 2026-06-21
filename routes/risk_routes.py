from collections import defaultdict
from datetime import datetime

from flask import Blueprint

from auth import login_required
from constants import Status
from storage import storage
from utils import ok, parse_args, name_of
from inspection_common import filter_inspections

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

    inspections = filter_inspections(storage.read("inspections"), args)
    scored = [i for i in inspections if i.get("total_score") is not None]
    now = datetime.now().isoformat(timespec="seconds")

    low_score_concentration = _low_score_concentration(scored, low_threshold, risk_ratio, min_sample)
    overdue_appeals = _overdue_appeals(args, now)
    frequent_items = _frequent_items(scored, frequent_threshold)
    missing_reviews = _missing_reviews(args)
    rising_risks = _rising_seat_group_risk(scored, low_threshold, risk_ratio, min_sample)

    summary = {
        "low_score_concentration": len(low_score_concentration),
        "overdue_appeals": len(overdue_appeals),
        "frequent_item_issues": len(frequent_items),
        "missing_review_conclusions": len(missing_reviews),
        "rising_seat_group_risk": len(rising_risks),
        "total_alerts": (len(low_score_concentration) + len(overdue_appeals)
                         + len(frequent_items) + len(missing_reviews) + len(rising_risks)),
    }
    return ok({"summary": summary, "alerts": {
        "low_score_concentration": low_score_concentration,
        "overdue_appeals": overdue_appeals,
        "frequent_item_issues": frequent_items,
        "missing_review_conclusions": missing_reviews,
        "rising_seat_group_risk": rising_risks,
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
