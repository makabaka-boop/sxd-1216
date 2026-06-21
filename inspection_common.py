from storage import storage


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
