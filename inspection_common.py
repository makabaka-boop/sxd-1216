from datetime import datetime, timedelta, timezone

from storage import storage, gen_id, now_iso
from constants import RectificationStatus, RectificationTrigger


def filter_inspections(inspections, args):
    items = list(inspections)
    if args.get("business_line_id"):
        items = [i for i in items if i.get("business_line_id") == args["business_line_id"]]
    if args.get("seat_group_id"):
        items = [i for i in items if i.get("seat_group_id") == args["seat_group_id"]]
    if args.get("inspector_id"):
        items = [i for i in items if i.get("inspector_id") == args["inspector_id"]]
    if args.get("status"):
        statuses = args["status"].split(",")
        items = [i for i in items if i.get("status") in statuses]
    if args.get("score_min") not in (None, ""):
        items = [i for i in items if i.get("total_score") is not None and i["total_score"] >= float(args["score_min"])]
    if args.get("score_max") not in (None, ""):
        items = [i for i in items if i.get("total_score") is not None and i["total_score"] <= float(args["score_max"])]
    if args.get("start_date"):
        items = [i for i in items if i.get("created_at", "") >= args["start_date"]]
    if args.get("end_date"):
        items = [i for i in items if i.get("created_at", "") <= args["end_date"]]
    return items


def compute_total_score(scoring_table, deductions):
    if not scoring_table:
        base = 100
    else:
        base = scoring_table.get("total_score", 100)
    deducted = sum(float(d.get("deducted", 0) or 0) for d in (deductions or []))
    return round(float(base) - deducted, 2)


def get_scoring_table(inspection):
    table_id = inspection.get("scoring_table_id")
    if not table_id:
        return None
    return storage.find("scoring_tables", table_id)


def enrich_inspection(inspection):
    if not inspection:
        return inspection
    inspection["business_line_name"] = _name("business_lines", inspection.get("business_line_id"))
    inspection["seat_group_name"] = _name("seat_groups", inspection.get("seat_group_id"))
    inspection["inspector_name"] = _name("users", inspection.get("inspector_id"), "name")
    inspection["scoring_table_name"] = _name("scoring_tables", inspection.get("scoring_table_id"))
    inspection["status_label"] = _status_label(inspection.get("status"))
    appeal = storage.find_one("appeals", lambda a: a.get("inspection_id") == inspection.get("id"))
    inspection["appeal_id"] = appeal["id"] if appeal else None
    rectifications = storage.find_all("rectifications", lambda r: r.get("inspection_id") == inspection.get("id"))
    for r in rectifications:
        enrich_rectification(r)
    inspection["rectifications"] = rectifications
    inspection["rectification_count"] = len(rectifications)
    if rectifications:
        latest = sorted(rectifications, key=lambda r: r.get("created_at", ""), reverse=True)[0]
        inspection["latest_rectification_status"] = latest.get("status")
        inspection["latest_rectification_status_label"] = latest.get("status_label")
    else:
        inspection["latest_rectification_status"] = None
        inspection["latest_rectification_status_label"] = None
    enrich_inspection_recurrence(inspection)
    return inspection


def enrich_appeal(appeal):
    if not appeal:
        return appeal
    appeal["inspection_call_id"] = _insp_field(appeal.get("inspection_id"), "call_id")
    appeal["seat_group_id"] = _insp_field(appeal.get("inspection_id"), "seat_group_id")
    appeal["seat_group_name"] = _name("seat_groups", appeal.get("seat_group_id"))
    appeal["business_line_id"] = _insp_field(appeal.get("inspection_id"), "business_line_id")
    appeal["business_line_name"] = _name("business_lines", appeal.get("business_line_id"))
    appeal["team_lead_name"] = _name("users", appeal.get("team_lead_id"), "name")
    appeal["status_label"] = _status_label(_insp_field(appeal.get("inspection_id"), "status"))
    return appeal


def enrich_rectification(rectification):
    if not rectification:
        return rectification
    rectification["business_line_name"] = _name("business_lines", rectification.get("business_line_id"))
    rectification["seat_group_name"] = _name("seat_groups", rectification.get("seat_group_id"))
    rectification["initiator_name"] = _name("users", rectification.get("initiator_id"), "name")
    rectification["assignee_name"] = _name("users", rectification.get("assignee_id"), "name")
    rectification["responsible_name"] = _name("users", rectification.get("responsible_user_id"), "name")
    rectification["acceptor_name"] = _name("users", rectification.get("acceptor_id"), "name")
    rectification["status_label"] = _rect_status_label(rectification.get("status"))
    rectification["trigger_label"] = _rect_trigger_label(rectification.get("trigger_reason"))
    if rectification.get("accept_result"):
        rectification["accept_result_label"] = _rect_accept_label(rectification.get("accept_result"))
    insp = storage.find("inspections", rectification.get("inspection_id"))
    rectification["call_id"] = insp.get("call_id") if insp else None
    rectification["agent_name"] = insp.get("agent_name") if insp else None
    rectification["inspection_score"] = insp.get("total_score") if insp else None
    appeal = storage.find_one("appeals", lambda a: a.get("inspection_id") == rectification.get("inspection_id"))
    rectification["appeal_id"] = appeal.get("id") if appeal else None
    review = storage.find_one("reviews", lambda r: r.get("inspection_id") == rectification.get("inspection_id"))
    rectification["review_id"] = review.get("id") if review else None
    _update_overdue_status(rectification)
    enrich_rectification_recurrence(rectification)
    return rectification


def _update_overdue_status(rectification):
    if rectification.get("status") in (
        RectificationStatus.COMPLETED,
        RectificationStatus.PENDING_ACCEPT,
    ):
        return
    deadline = rectification.get("plan_deadline")
    if not deadline:
        return
    now = now_iso()
    if now > deadline and rectification.get("status") not in (RectificationStatus.OVERDUE,):
        rectification["status"] = RectificationStatus.OVERDUE
        rectification["status_label"] = RectificationStatus.LABELS[RectificationStatus.OVERDUE]
        storage.update("rectifications", rectification["id"], {"status": RectificationStatus.OVERDUE})


def _rect_status_label(status):
    return RectificationStatus.LABELS.get(status, status)


def _rect_trigger_label(trigger):
    return RectificationTrigger.LABELS.get(trigger, trigger)


def _rect_accept_label(result):
    from constants import RectificationAcceptResult
    return RectificationAcceptResult.LABELS.get(result, result)


def _name(collection, record_id, field="name"):
    if not record_id:
        return None
    rec = storage.find(collection, record_id)
    return rec.get(field) if rec else None


def _insp_field(inspection_id, field):
    insp = storage.find("inspections", inspection_id) if inspection_id else None
    return insp.get(field) if insp else None


def _status_label(status):
    from constants import Status
    return Status.LABELS.get(status, status)


def _rect_deadline_hours():
    cfg = storage.read("config") or {}
    return int(cfg.get("rectify_deadline_hours", 72))


def _compute_rect_deadline():
    return (datetime.now(timezone.utc) + timedelta(hours=_rect_deadline_hours())).isoformat(timespec="seconds")


def _has_key_deduction(inspection):
    cfg = storage.read("config") or {}
    key_item_ids = cfg.get("key_deduction_item_ids") or []
    key_threshold = float(cfg.get("key_deduction_threshold_score", 5))
    deductions = inspection.get("deductions") or []
    for d in deductions:
        item_id = d.get("item_id")
        deducted = float(d.get("deducted", 0) or 0)
        if key_item_ids and item_id in key_item_ids and deducted > 0:
            return True
        if deducted >= key_threshold:
            return True
    return False


def _low_score_trigger(inspection):
    cfg = storage.read("config") or {}
    if not cfg.get("rectify_auto_trigger_low_score", True):
        return False
    low_threshold = float(cfg.get("low_score_threshold", 80))
    score = inspection.get("total_score")
    return score is not None and float(score) < low_threshold


def _key_deduction_trigger(inspection):
    cfg = storage.read("config") or {}
    if not cfg.get("rectify_auto_trigger_key_deduction", True):
        return False
    return _has_key_deduction(inspection)


def determine_triggers(inspection, context="close"):
    if context == "review":
        return [RectificationTrigger.REVIEW_UPHELD]
    triggers = []
    if _low_score_trigger(inspection):
        triggers.append(RectificationTrigger.LOW_SCORE)
    if _key_deduction_trigger(inspection):
        triggers.append(RectificationTrigger.KEY_DEDUCTION)
    return triggers


def auto_create_rectification(inspection, initiator_id, triggers=None, context="close"):
    if not triggers:
        triggers = determine_triggers(inspection, context=context)
    if not triggers:
        return None
    existing = storage.find_one("rectifications", lambda r: (
        r.get("inspection_id") == inspection.get("id")
        and r.get("status") not in (RectificationStatus.COMPLETED,)
    ))
    if existing:
        return None
    seat_group_id = inspection.get("seat_group_id")
    assignee_id = None
    if seat_group_id:
        sg = storage.find("seat_groups", seat_group_id)
        if sg:
            assignee_id = sg.get("leader_id")
    trigger_reason = triggers[0]
    if len(triggers) > 1:
        if RectificationTrigger.REVIEW_UPHELD in triggers:
            trigger_reason = RectificationTrigger.REVIEW_UPHELD
    rectification = {
        "id": gen_id("rect"),
        "inspection_id": inspection.get("id"),
        "business_line_id": inspection.get("business_line_id"),
        "seat_group_id": seat_group_id,
        "initiator_id": initiator_id,
        "assignee_id": assignee_id,
        "trigger_reason": trigger_reason,
        "trigger_reasons": triggers,
        "status": RectificationStatus.PENDING_RECTIFY,
        "title": _build_rectification_title(inspection, triggers),
        "description": _build_rectification_description(inspection, triggers),
        "rectify_measures": None,
        "responsible_user_id": None,
        "plan_deadline": _compute_rect_deadline(),
        "rectify_note": None,
        "attachment_link": None,
        "submitted_at": None,
        "acceptor_id": None,
        "accept_result": None,
        "accept_note": None,
        "accepted_at": None,
        "reminders": [],
        "reject_count": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    storage.insert("rectifications", rectification)
    enrich_rectification(rectification)
    return rectification


def manual_create_rectification(inspection_id, initiator_id, body):
    insp = storage.find("inspections", inspection_id)
    if not insp:
        return None, "抽检记录不存在"
    seat_group_id = body.get("seat_group_id") or insp.get("seat_group_id")
    assignee_id = body.get("assignee_id")
    if not assignee_id and seat_group_id:
        sg = storage.find("seat_groups", seat_group_id)
        if sg:
            assignee_id = sg.get("leader_id")
    plan_deadline = body.get("plan_deadline") or _compute_rect_deadline()
    rectification = {
        "id": gen_id("rect"),
        "inspection_id": inspection_id,
        "business_line_id": body.get("business_line_id") or insp.get("business_line_id"),
        "seat_group_id": seat_group_id,
        "initiator_id": initiator_id,
        "assignee_id": assignee_id,
        "trigger_reason": RectificationTrigger.MANUAL,
        "trigger_reasons": [RectificationTrigger.MANUAL],
        "status": RectificationStatus.PENDING_RECTIFY,
        "title": (body.get("title") or "").strip() or f"手动整改-{insp.get('call_id','')}",
        "description": (body.get("description") or "").strip(),
        "rectify_measures": None,
        "responsible_user_id": body.get("responsible_user_id"),
        "plan_deadline": plan_deadline,
        "rectify_note": None,
        "attachment_link": None,
        "submitted_at": None,
        "acceptor_id": None,
        "accept_result": None,
        "accept_note": None,
        "accepted_at": None,
        "reminders": [],
        "reject_count": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    storage.insert("rectifications", rectification)
    enrich_rectification(rectification)
    return rectification, None


def _build_rectification_title(inspection, triggers):
    parts = []
    for t in triggers:
        parts.append(RectificationTrigger.LABELS.get(t, t))
    reason_str = "+".join(parts) if parts else "整改"
    return f"{reason_str}-{inspection.get('call_id', '')}"


def _build_rectification_description(inspection, triggers):
    lines = []
    lines.append(f"关联抽检单号：{inspection.get('id')}")
    if inspection.get("call_id"):
        lines.append(f"通话编号：{inspection['call_id']}")
    if inspection.get("total_score") is not None:
        lines.append(f"质检得分：{inspection['total_score']}")
    deductions = inspection.get("deductions") or []
    if deductions:
        lines.append("扣分项：")
        for d in deductions:
            lines.append(f"  - {d.get('item_name', d.get('item_id', ''))}: -{d.get('deducted', 0)}分")
    if inspection.get("suggestion"):
        lines.append(f"质检建议：{inspection['suggestion']}")
    return "\n".join(lines)


def _recurrence_config():
    cfg = storage.read("config") or {}
    return {
        "observation_days": int(cfg.get("recurrence_observation_days", 30)),
        "criteria": cfg.get("recurrence_criteria", "seat_group_item"),
        "alert_threshold": int(cfg.get("recurrence_alert_threshold", 2)),
    }


def _within_observation(target_date_str, observation_days):
    if not target_date_str:
        return False
    try:
        target = datetime.fromisoformat(target_date_str)
    except Exception:
        return False
    now = datetime.now()
    delta = now - target
    return delta.total_seconds() <= observation_days * 24 * 3600


def _match_criteria(criteria, rect_a, rect_b, inspection_a, inspection_b):
    if criteria == "seat_group_item":
        sg_a = rect_a.get("seat_group_id") or inspection_a.get("seat_group_id")
        sg_b = rect_b.get("seat_group_id") or inspection_b.get("seat_group_id")
        if sg_a != sg_b:
            return False
        items_a = {d.get("item_id") for d in (inspection_a.get("deductions") or [])}
        items_b = {d.get("item_id") for d in (inspection_b.get("deductions") or [])}
        return bool(items_a & items_b)
    elif criteria == "agent_item":
        agent_a = inspection_a.get("agent_name")
        agent_b = inspection_b.get("agent_name")
        if agent_a != agent_b or not agent_a:
            return False
        items_a = {d.get("item_id") for d in (inspection_a.get("deductions") or [])}
        items_b = {d.get("item_id") for d in (inspection_b.get("deductions") or [])}
        return bool(items_a & items_b)
    elif criteria == "seat_group_any":
        sg_a = rect_a.get("seat_group_id") or inspection_a.get("seat_group_id")
        sg_b = rect_b.get("seat_group_id") or inspection_b.get("seat_group_id")
        return sg_a == sg_b and sg_a is not None
    elif criteria == "business_line_item":
        bl_a = rect_a.get("business_line_id") or inspection_a.get("business_line_id")
        bl_b = rect_b.get("business_line_id") or inspection_b.get("business_line_id")
        if bl_a != bl_b:
            return False
        items_a = {d.get("item_id") for d in (inspection_a.get("deductions") or [])}
        items_b = {d.get("item_id") for d in (inspection_b.get("deductions") or [])}
        return bool(items_a & items_b)
    return False


def _overlapping_deduction_items(insp_a, insp_b):
    items_a = {d.get("item_id"): d for d in (insp_a.get("deductions") or [])}
    items_b = {d.get("item_id"): d for d in (insp_b.get("deductions") or [])}
    overlap = []
    for item_id in items_a:
        if item_id in items_b:
            overlap.append({
                "item_id": item_id,
                "item_name": items_a[item_id].get("item_name") or items_b[item_id].get("item_name"),
                "deducted_a": items_a[item_id].get("deducted", 0),
                "deducted_b": items_b[item_id].get("deducted", 0),
            })
    return overlap


def detect_inspection_recurrence(inspection):
    cfg = _recurrence_config()
    observation_days = cfg["observation_days"]
    criteria = cfg["criteria"]
    all_rects = storage.read("rectifications")
    all_insp = {i["id"]: i for i in storage.read("inspections")}
    matched = []
    current_insp_id = inspection.get("id")
    for r in all_rects:
        if r.get("inspection_id") == current_insp_id:
            continue
        if not _within_observation(r.get("created_at"), observation_days):
            continue
        r_insp = all_insp.get(r.get("inspection_id"))
        if not r_insp:
            continue
        dummy_rect = {
            "seat_group_id": inspection.get("seat_group_id"),
            "business_line_id": inspection.get("business_line_id"),
        }
        if _match_criteria(criteria, dummy_rect, r, inspection, r_insp):
            overlap_items = _overlapping_deduction_items(inspection, r_insp)
            matched.append({
                "rectification": r,
                "inspection": r_insp,
                "overlap_items": overlap_items,
            })
    if not matched:
        return {
            "is_recurrence": False,
            "recurrence_count": 0,
            "latest_recurrence_at": None,
            "recurrence_items": [],
            "related_rectifications": [],
        }
    matched.sort(key=lambda m: m["rectification"].get("created_at", ""), reverse=True)
    latest = matched[0]
    all_overlap_items = []
    seen = set()
    for m in matched:
        for it in m["overlap_items"]:
            if it["item_id"] not in seen:
                seen.add(it["item_id"])
                all_overlap_items.append(it)
    related_rects = []
    for m in matched:
        r = m["rectification"]
        r_insp = m["inspection"]
        related_rects.append({
            "rectification_id": r.get("id"),
            "inspection_id": r.get("inspection_id"),
            "call_id": r_insp.get("call_id"),
            "created_at": r.get("created_at"),
            "status": r.get("status"),
            "status_label": RectificationStatus.LABELS.get(r.get("status"), r.get("status")),
            "accept_result": r.get("accept_result"),
            "overlap_items": m["overlap_items"],
        })
    return {
        "is_recurrence": True,
        "recurrence_count": len(matched),
        "latest_recurrence_at": latest["rectification"].get("created_at"),
        "latest_rectification_id": latest["rectification"].get("id"),
        "latest_rectification_status": latest["rectification"].get("status"),
        "latest_rectification_status_label": RectificationStatus.LABELS.get(
            latest["rectification"].get("status"), latest["rectification"].get("status")
        ),
        "latest_accept_result": latest["rectification"].get("accept_result"),
        "recurrence_items": all_overlap_items,
        "related_rectifications": related_rects,
    }


def detect_rectification_recurrence(rectification):
    inspection = storage.find("inspections", rectification.get("inspection_id"))
    if not inspection:
        return {
            "is_recurrence": False,
            "recurrence_count": 0,
            "latest_recurrence_at": None,
            "recurrence_items": [],
            "related_rectifications": [],
        }
    info = detect_inspection_recurrence(inspection)
    current_id = rectification.get("id")
    info["related_rectifications"] = [
        r for r in info["related_rectifications"] if r["rectification_id"] != current_id
    ]
    info["recurrence_count"] = len(info["related_rectifications"])
    if info["recurrence_count"] == 0:
        info["is_recurrence"] = False
        info["latest_recurrence_at"] = None
        info["latest_rectification_id"] = None
        info["latest_rectification_status"] = None
        info["latest_rectification_status_label"] = None
        info["latest_accept_result"] = None
        info["recurrence_items"] = []
    return info


def enrich_inspection_recurrence(inspection):
    if not inspection:
        return inspection
    info = detect_inspection_recurrence(inspection)
    inspection["is_recurrence"] = info["is_recurrence"]
    inspection["recurrence_count"] = info["recurrence_count"]
    inspection["latest_recurrence_at"] = info.get("latest_recurrence_at")
    inspection["latest_rectification_id"] = info.get("latest_rectification_id")
    inspection["latest_rectification_status"] = info.get("latest_rectification_status")
    inspection["latest_rectification_status_label"] = info.get("latest_rectification_status_label")
    inspection["latest_accept_result"] = info.get("latest_accept_result")
    inspection["recurrence_items"] = info.get("recurrence_items", [])
    inspection["related_rectifications"] = info.get("related_rectifications", [])
    return inspection


def enrich_rectification_recurrence(rectification):
    if not rectification:
        return rectification
    info = detect_rectification_recurrence(rectification)
    rectification["is_recurrence"] = info["is_recurrence"]
    rectification["recurrence_count"] = info["recurrence_count"]
    rectification["latest_recurrence_at"] = info.get("latest_recurrence_at")
    rectification["latest_rectification_id"] = info.get("latest_rectification_id")
    rectification["latest_rectification_status"] = info.get("latest_rectification_status")
    rectification["latest_rectification_status_label"] = info.get("latest_rectification_status_label")
    rectification["latest_accept_result"] = info.get("latest_accept_result")
    rectification["recurrence_items"] = info.get("recurrence_items", [])
    rectification["related_rectifications"] = info.get("related_rectifications", [])
    return rectification
