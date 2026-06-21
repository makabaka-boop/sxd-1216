from flask import jsonify, request

from storage import storage


def ok(data=None, message="success"):
    payload = {"code": 0, "message": message}
    if data is not None:
        payload["data"] = data
    return jsonify(payload)


def fail(message, code=400):
    return jsonify({"code": code, "message": message}), code


def get_json_body():
    return request.get_json(silent=True) or {}


def parse_args():
    return request.args.to_dict(flat=True)


def name_of(collection, record_id, name_field="name"):
    if not record_id:
        return None
    rec = storage.find(collection, record_id)
    if not rec:
        return None
    return rec.get(name_field)


def paginate(items, page, page_size):
    page = max(int(page or 1), 1)
    page_size = max(min(int(page_size or 20), 200), 1)
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "items": items[start:end],
        "page": page,
        "page_size": page_size,
        "total": total,
    }
