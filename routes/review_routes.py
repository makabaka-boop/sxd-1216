from flask import Blueprint, g

from auth import role_required, login_required
from constants import Status, Role
from storage import storage, gen_id, now_iso
from utils import ok, fail, get_json_body, parse_args, paginate
from inspection_common import enrich_inspection

bp = Blueprint("review", __name__, url_prefix="/api/reviews")


@bp.post("")
@role_required(Role.ADMIN, Role.INSPECTOR)
def submit_review():
    body = get_json_body()
    inspection_id = body.get("inspection_id")
    insp = storage.find("inspections", inspection_id) if inspection_id else None
    if not insp:
        return fail("抽检记录不存在", 404)
    if insp["status"] != Status.PENDING_REVIEW:
        return fail("仅待复核状态可提交复核结论")
    if g.current_user["role"] == Role.INSPECTOR and insp.get("inspector_id") == g.current_user["id"]:
        return fail("不可复核本人提交的质检记录")
    conclusion = (body.get("conclusion") or "").strip()
    if not conclusion:
        return fail("复核结论不能为空")
    review = {
        "id": gen_id("rev"),
        "inspection_id": inspection_id,
        "reviewer_id": g.current_user["id"],
        "conclusion": conclusion,
        "adjusted_score": body.get("adjusted_score"),
        "created_at": now_iso(),
    }
    storage.insert("reviews", review)
    patch = {"status": Status.CLOSED}
    if body.get("adjusted_score") is not None:
        patch["total_score"] = body.get("adjusted_score")
    insp = storage.update("inspections", inspection_id, patch)
    appeal = storage.find_one("appeals", lambda a: a.get("inspection_id") == inspection_id)
    if appeal and not appeal.get("closed_at"):
        storage.update("appeals", appeal["id"], {"closed_at": now_iso()})
    enrich_inspection(insp)
    return ok({"review": review, "inspection": insp}, "复核完成，已结案")


@bp.get("")
@login_required
def list_reviews():
    args = parse_args()
    items = storage.read("reviews")
    if args.get("inspection_id"):
        items = [r for r in items if r.get("inspection_id") == args["inspection_id"]]
    items.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    for r in items:
        reviewer = storage.find("users", r.get("reviewer_id"))
        r["reviewer_name"] = reviewer.get("name") if reviewer else None
        insp = storage.find("inspections", r.get("inspection_id"))
        r["call_id"] = insp.get("call_id") if insp else None
    return ok(paginate(items, args.get("page"), args.get("page_size")))
