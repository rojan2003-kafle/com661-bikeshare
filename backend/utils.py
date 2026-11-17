import math
import re
from datetime import datetime, timezone

from bson import ObjectId
from flask import request, make_response, jsonify


class ApiError(Exception):
    """raise ApiError(400, "message") anywhere -> app.py turns it into a JSON error"""
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def now():
    return datetime.now(timezone.utc)


def to_json(value):
    """MongoDB gives us ObjectId and datetime objects - jsonify can't handle those,
    so convert them to strings (and never send password hashes back)"""
    if isinstance(value, dict):
        return {k: to_json(v) for k, v in value.items() if k != "password_hash"}
    if isinstance(value, list):
        return [to_json(v) for v in value]
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return value


def respond(body, status=200):
    return make_response(jsonify(to_json(body)), status)


# ---------------- validators: check type AND range ----------------
def parse_int(value, name, min_val=None, max_val=None):
    try:
        number = int(str(value).strip())
    except ValueError:
        raise ApiError(400, f"'{name}' must be a whole number")
    if min_val is not None and number < min_val:
        raise ApiError(400, f"'{name}' must be at least {min_val}")
    if max_val is not None and number > max_val:
        raise ApiError(400, f"'{name}' must be no more than {max_val}")
    return number


def parse_enum(value, name, allowed):
    value = str(value).strip().lower()
    if value not in allowed:
        raise ApiError(400, f"'{name}' must be one of: {', '.join(allowed)}")
    return value


def check_id(value, prefix, name):
    """our IDs look like ST001, BK0001, U001 ..."""
    if not re.fullmatch(prefix + r"\d{3,6}", value):
        raise ApiError(400, f"Invalid {name} ID format '{value}' (expected e.g. {prefix}001)")
    return value


# ---------------- pagination ----------------
def get_pagination(default_size=10, max_size=100):
    page_num = parse_int(request.args.get("pn", 1), "pn", 1)
    page_size = parse_int(request.args.get("ps", default_size), "ps", 1, max_size)
    return page_num, page_size, (page_num - 1) * page_size


def paged_response(items, total, page_num, page_size):
    return {"page": page_num, "page_size": page_size, "total": total,
            "total_pages": math.ceil(total / page_size), "data": items}

# ---------------- reading the request body ----------------
def get_data():
    """accept form-data (like the module) OR a JSON body"""
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return request.form.to_dict()


def require_fields(data, fields):
    missing = [f for f in fields if f not in data or str(data[f]).strip() == ""]
    if missing:
        raise ApiError(400, "Missing required field(s): " + ", ".join(missing))


def parse_str(value, name, min_len=1, max_len=200):
    value = str(value).strip()
    if not (min_len <= len(value) <= max_len):
        raise ApiError(400, f"'{name}' must be between {min_len} and {max_len} characters")
    return value


def parse_email(value):
    value = parse_str(value, "email", 5, 120).lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$", value):
        raise ApiError(400, "'email' is not a valid email address")
    return value


def parse_password(value):
    value = parse_str(value, "password", 8, 64)
    if not (re.search(r"[A-Za-z]", value) and re.search(r"\d", value)):
        raise ApiError(400, "'password' must contain at least one letter and one number")
    return value


# ---------------- readable IDs: U151, ST121, BK0901 ----------------
def next_id(counter_name, collection, field, prefix, width):
    import globals
    from pymongo import ReturnDocument
    if globals.counters.find_one({"_id": counter_name}) is None:
        # first time: start counting from the highest ID already in the collection
        last = collection.find_one({field: {"$regex": "^" + prefix}}, sort=[(field, -1)])
        start = int(last[field][len(prefix):]) if last else 0
        globals.counters.insert_one({"_id": counter_name, "seq": start})
    # $inc is atomic: two requests at the same time never get the same number
    doc = globals.counters.find_one_and_update(
        {"_id": counter_name}, {"$inc": {"seq": 1}}, return_document=ReturnDocument.AFTER)
    return f"{prefix}{doc['seq']:0{width}d}"


def parse_float(value, name, min_val=None, max_val=None):
    try:
        number = float(str(value).strip())
    except ValueError:
        raise ApiError(400, f"'{name}' must be a number")
    if min_val is not None and number < min_val:
        raise ApiError(400, f"'{name}' must be at least {min_val}")
    if max_val is not None and number > max_val:
        raise ApiError(400, f"'{name}' must be no more than {max_val}")
    return number
