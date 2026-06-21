from collections import defaultdict
from datetime import datetime

from flask import Blueprint

from auth import login_required
from storage import storage
from utils import ok, parse_args, name_of
from inspection_common import filter_inspections, enrich_inspection, enrich_appeal

bp = Blueprint("stats", __name__, url_prefix="/api/stats")


def _cfg():
    return storage.read("config") or {}


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
