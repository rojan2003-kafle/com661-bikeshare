from flask import Blueprint, request
import globals
from decorators import jwt_required, role_required
from utils import (ApiError, respond, get_data, require_fields, parse_int, parse_enum,
                   check_id, get_pagination, paged_response, next_id)

bikes_bp = Blueprint("bikes_bp", __name__)

TYPES = ["standard", "electric"]
STATUSES = ["available", "in_use", "reserved", "under_repair"]


def find_bike(bike_id):
    check_id(bike_id, "BK", "bike")
    bike = globals.bikes.find_one({"bike_id": bike_id}, {"_id": 0})
    if bike is None:
        raise ApiError(404, f"Bike {bike_id} not found")
    return bike


def check_free_dock(station_id):
    """a bike can only be placed at a station that exists and has an empty dock"""
    check_id(station_id, "ST", "station")
    station = globals.stations.find_one({"station_id": station_id})
    if station is None:
        raise ApiError(404, f"Station {station_id} not found")
    docked = globals.bikes.count_documents({"station_id": station_id})
    if docked >= station["total_docks"]:
        raise ApiError(409, f"Station {station_id} is full ({docked}/{station['total_docks']} docks used)")


# ---------- GET all bikes with filters: ?status=&type=&station_id=&min_battery= ----------
@bikes_bp.route("/bikes", methods=["GET"])
@jwt_required
def show_all_bikes():
    page_num, page_size, page_start = get_pagination()
    query = {}
    if request.args.get("status"):
        query["status"] = parse_enum(request.args["status"], "status", STATUSES)
    if request.args.get("type"):
        query["type"] = parse_enum(request.args["type"], "type", TYPES)
    if request.args.get("station_id"):
        query["station_id"] = check_id(request.args["station_id"], "ST", "station")
    if request.args.get("min_battery"):
        query["battery_level"] = {"$gte": parse_int(request.args["min_battery"], "min_battery", 0, 100)}

    total = globals.bikes.count_documents(query)
    data = list(globals.bikes.find(query, {"_id": 0}).sort("bike_id", 1).skip(page_start).limit(page_size))
    return respond(paged_response(data, total, page_num, page_size), 200)


@bikes_bp.route("/bikes/<string:bike_id>", methods=["GET"])
@jwt_required
def show_one_bike(bike_id):
    return respond(find_bike(bike_id), 200)


# ---------- ADMIN: add / edit / delete ----------
@bikes_bp.route("/bikes", methods=["POST"])
@role_required("admin")
def add_bike():
    data = get_data()
    require_fields(data, ["type", "station_id"])
    bike_type = parse_enum(data["type"], "type", TYPES)
    station_id = str(data["station_id"]).strip()
    check_free_dock(station_id)

    battery = None
    if bike_type == "electric":
        battery = parse_int(data.get("battery_level", 100), "battery_level", 0, 100)
    elif data.get("battery_level"):
        raise ApiError(400, "'battery_level' only applies to electric bikes")

    new_bike = {"bike_id": next_id("bikes", globals.bikes, "bike_id", "BK", 4),
                "station_id": station_id, "type": bike_type,
                "battery_level": battery, "status": "available"}
    globals.bikes.insert_one(new_bike)
    new_bike.pop("_id", None)
    return respond({"message": "Bike added",
                    "url": request.host_url + "api/v1.0/bikes/" + new_bike["bike_id"],
                    "bike": new_bike}, 201)


@bikes_bp.route("/bikes/<string:bike_id>", methods=["PUT"])
@role_required("admin")
def edit_bike(bike_id):
    """admin can move a bike (rebalancing), change its battery or take it out of service"""
    bike = find_bike(bike_id)
    if bike["status"] in ("in_use", "reserved"):
        raise ApiError(409, f"Bike {bike_id} is {bike['status']} - wait until the ride ends")
    data = get_data()
    changes = {}
    if "battery_level" in data:
        if bike["type"] != "electric":
            raise ApiError(400, "'battery_level' only applies to electric bikes")
        changes["battery_level"] = parse_int(data["battery_level"], "battery_level", 0, 100)
    if "status" in data:
        changes["status"] = parse_enum(data["status"], "status", ["available", "under_repair"])
    if "station_id" in data:
        new_station = str(data["station_id"]).strip()
        if new_station != bike["station_id"]:
            check_free_dock(new_station)
        changes["station_id"] = new_station
    if not changes:
        raise ApiError(400, "Nothing to update - send battery_level, status and/or station_id")
    globals.bikes.update_one({"bike_id": bike_id}, {"$set": changes})
    return respond({"message": "Bike updated", "bike": find_bike(bike_id)}, 200)


@bikes_bp.route("/bikes/<string:bike_id>", methods=["DELETE"])
@role_required("admin")
def delete_bike(bike_id):
    bike = find_bike(bike_id)
    if bike["status"] in ("in_use", "reserved"):
        raise ApiError(409, f"Bike {bike_id} is {bike['status']} and can't be deleted right now")
    globals.bikes.delete_one({"bike_id": bike_id})
    return respond({}, 204)
