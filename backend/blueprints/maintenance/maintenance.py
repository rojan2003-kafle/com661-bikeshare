from bson import ObjectId
from flask import Blueprint, request, g
import globals
from decorators import jwt_required, role_required
from utils import (ApiError, respond, get_data, require_fields, parse_str, parse_enum,
                   check_id, get_pagination, paged_response, next_id, now)
from blueprints.bikes.bikes import find_bike

maintenance_bp = Blueprint("maintenance_bp", __name__)

ISSUES = ["brakes", "tyre", "chain", "battery", "other"]


def find_report(report_id):
    check_id(report_id, "MR", "report")
    report = globals.maintenance.find_one({"report_id": report_id}, {"_id": 0})
    if report is None:
        raise ApiError(404, f"Maintenance report {report_id} not found")
    return report


def check_note_id(note_id):
    if not ObjectId.is_valid(note_id):
        raise ApiError(400, f"Invalid note ID '{note_id}'")
    return ObjectId(note_id)


# ---------- rider: report a fault ----------
@maintenance_bp.route("/maintenance/report", methods=["POST"])
@jwt_required
def report_fault():
    data = get_data()
    require_fields(data, ["bike_id", "issue_type"])
    bike = find_bike(str(data["bike_id"]).strip())
    issue = parse_enum(data["issue_type"], "issue_type", ISSUES)
    if issue == "battery" and bike["type"] != "electric":
        raise ApiError(400, "Battery faults can only be reported on electric bikes")
    if bike["status"] == "in_use":
        raise ApiError(409, "Please return the bike first, then report the fault")
    description = parse_str(data.get("description", f"{issue} problem"), "description", 3, 500)

    if globals.maintenance.find_one({"bike_id": bike["bike_id"], "issue_type": issue,
                                     "status": {"$in": ["open", "in_progress"]}}):
        raise ApiError(409, f"A {issue} fault is already open for bike {bike['bike_id']}")

    report = {"report_id": next_id("maintenance", globals.maintenance, "report_id", "MR", 4),
              "bike_id": bike["bike_id"], "reported_by": g.user_id, "issue_type": issue,
              "description": description, "status": "open", "assigned_to": None,
              "created_at": now(), "resolved_at": None, "notes": []}
    globals.maintenance.insert_one(report)
    report.pop("_id", None)
    # take the bike out of service straight away
    globals.bikes.update_one({"bike_id": bike["bike_id"]}, {"$set": {"status": "under_repair"}})
    return respond({"message": "Thank you - the bike has been taken out of service", "report": report}, 201)


# ---------- mechanic: task list ----------
@maintenance_bp.route("/maintenance/open", methods=["GET"])
@role_required("mechanic", "admin")
def open_faults():
    """?issue_type=&status=open|in_progress  - joined with bike + station so the mechanic knows where to go"""
    page_num, page_size, page_start = get_pagination()
    match = {"status": {"$in": ["open", "in_progress"]}}
    if request.args.get("status"):
        match["status"] = parse_enum(request.args["status"], "status", ["open", "in_progress"])
    if request.args.get("issue_type"):
        match["issue_type"] = parse_enum(request.args["issue_type"], "issue_type", ISSUES)

    result = list(globals.maintenance.aggregate([
        {"$match": match},
        {"$lookup": {"from": "bikes", "localField": "bike_id", "foreignField": "bike_id", "as": "bike"}},
        {"$addFields": {"station_id": {"$arrayElemAt": ["$bike.station_id", 0]}}},
        {"$lookup": {"from": "stations", "localField": "station_id", "foreignField": "station_id", "as": "st"}},
        {"$addFields": {"station_name": {"$arrayElemAt": ["$st.name", 0]}, "note_count": {"$size": "$notes"}}},
        {"$project": {"_id": 0, "bike": 0, "st": 0, "notes": 0}},
        {"$facet": {
            "data": [{"$sort": {"created_at": 1}}, {"$skip": page_start}, {"$limit": page_size}],
            "total": [{"$count": "count"}],
        }},
    ]))[0]
    total = result["total"][0]["count"] if result["total"] else 0
    return respond(paged_response(result["data"], total, page_num, page_size), 200)


@maintenance_bp.route("/maintenance/<string:report_id>", methods=["GET"])
@role_required("mechanic", "admin")
def get_one_report(report_id):
    return respond(find_report(report_id), 200)


@maintenance_bp.route("/maintenance/<string:report_id>/assign", methods=["PATCH"])
@role_required("mechanic")
def assign_report(report_id):
    report = find_report(report_id)
    if report["status"] == "resolved":
        raise ApiError(409, "This report is already resolved")
    globals.maintenance.update_one({"report_id": report_id},
                                   {"$set": {"assigned_to": g.user_id, "status": "in_progress"}})
    return respond({"message": f"Report assigned to you ({g.user_id})", "report": find_report(report_id)}, 200)


@maintenance_bp.route("/maintenance/<string:report_id>/resolve", methods=["PATCH"])
@role_required("mechanic", "admin")
def resolve_report(report_id):
    report = find_report(report_id)
    if report["status"] == "resolved":
        raise ApiError(409, "This report is already resolved")
    globals.maintenance.update_one({"report_id": report_id}, {"$set": {
        "status": "resolved", "resolved_at": now(), "assigned_to": report["assigned_to"] or g.user_id}})
    # bike goes back into service only if it has no OTHER unresolved faults
    still_open = globals.maintenance.count_documents(
        {"bike_id": report["bike_id"], "status": {"$in": ["open", "in_progress"]}})
    changes = {}
    if still_open == 0:
        changes["status"] = "available"
    if report["issue_type"] == "battery":
        changes["battery_level"] = 100
    if changes:
        globals.bikes.update_one({"bike_id": report["bike_id"]}, {"$set": changes})
    return respond({"message": "Fault resolved", "bike": find_bike(report["bike_id"])}, 200)


# ================= NOTES: full CRUD on a sub-document array =================
@maintenance_bp.route("/maintenance/<string:report_id>/notes", methods=["GET"])
@role_required("mechanic", "admin")
def get_notes(report_id):
    report = find_report(report_id)
    return respond({"report_id": report_id, "count": len(report["notes"]), "notes": report["notes"]}, 200)


@maintenance_bp.route("/maintenance/<string:report_id>/notes", methods=["POST"])
@role_required("mechanic", "admin")
def add_note(report_id):
    find_report(report_id)
    data = get_data()
    require_fields(data, ["note"])
    note = {"_id": ObjectId(), "mechanic_id": g.user_id,
            "note": parse_str(data["note"], "note", 2, 500), "created_at": now()}
    # $push adds one element to the notes array
    globals.maintenance.update_one({"report_id": report_id}, {"$push": {"notes": note}})
    return respond({"message": "Note added", "note": note}, 201)


@maintenance_bp.route("/maintenance/<string:report_id>/notes/<string:note_id>", methods=["GET"])
@role_required("mechanic", "admin")
def get_one_note(report_id, note_id):
    oid = check_note_id(note_id)
    find_report(report_id)
    # $elemMatch projection returns ONLY the matching element of the array
    doc = globals.maintenance.find_one({"report_id": report_id},
                                       {"_id": 0, "notes": {"$elemMatch": {"_id": oid}}})
    if not doc or not doc.get("notes"):
        raise ApiError(404, f"Note {note_id} not found")
    return respond(doc["notes"][0], 200)


@maintenance_bp.route("/maintenance/<string:report_id>/notes/<string:note_id>", methods=["PUT"])
@role_required("mechanic", "admin")
def edit_note(report_id, note_id):
    oid = check_note_id(note_id)
    find_report(report_id)
    data = get_data()
    require_fields(data, ["note"])
    # the positional operator $ means "the array element that matched the query"
    result = globals.maintenance.update_one(
        {"report_id": report_id, "notes._id": oid},
        {"$set": {"notes.$.note": parse_str(data["note"], "note", 2, 500), "notes.$.edited_at": now()}})
    if result.matched_count == 0:
        raise ApiError(404, f"Note {note_id} not found")
    return respond({"message": "Note updated"}, 200)


@maintenance_bp.route("/maintenance/<string:report_id>/notes/<string:note_id>", methods=["DELETE"])
@role_required("mechanic", "admin")
def delete_note(report_id, note_id):
    oid = check_note_id(note_id)
    find_report(report_id)
    # $pull removes the array element that matches
    result = globals.maintenance.update_one({"report_id": report_id}, {"$pull": {"notes": {"_id": oid}}})
    if result.modified_count == 0:
        raise ApiError(404, f"Note {note_id} not found")
    return respond({}, 204)
