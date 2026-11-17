import math
from datetime import timedelta

from flask import Blueprint, request, g
from pymongo import ReturnDocument

import globals
from decorators import jwt_required, role_required
from utils import (ApiError, respond, get_data, require_fields, check_id,
                   get_pagination, paged_response, next_id, now)
from blueprints.bikes.bikes import find_bike

rentals_bp = Blueprint("rentals_bp", __name__)

# ---------- pricing ----------
UNLOCK_FEE = 1.00
PER_MIN = {"standard": 0.05, "electric": 0.20}
OUTER_ZONE_DISCOUNT = 0.10        # 10% off rides starting in the outer zone
RESERVATION_MINUTES = 10
MIN_BATTERY = 20


def calculate_cost(bike_type, minutes, zone):
    cost = UNLOCK_FEE + PER_MIN[bike_type] * minutes
    if zone == "outer":
        cost *= (1 - OUTER_ZONE_DISCOUNT)
    return round(cost, 2)


def haversine_km(lat1, lng1, lat2, lng2):
    """straight-line distance between two GPS points on the Earth"""
    r = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ---------- helpers ----------
def expire_old_reservations():
    """reservations past their 10 minutes are cancelled and the bike freed (lazy expiry)"""
    for r in globals.rentals.find({"status": "reserved", "expires_at": {"$lt": now()}}):
        globals.rentals.update_one({"rental_id": r["rental_id"]},
                                   {"$set": {"status": "cancelled", "cancel_reason": "expired"}})
        globals.bikes.update_one({"bike_id": r["bike_id"], "status": "reserved"},
                                 {"$set": {"status": "available"}})


def check_no_open_rental(user_id):
    current = globals.rentals.find_one({"user_id": user_id, "status": {"$in": ["reserved", "active"]}})
    if current:
        raise ApiError(409, f"You already have a {current['status']} rental ({current['rental_id']}) "
                            "- finish or cancel it first")


def grab_bike(bike_id, new_status):
    """
    ATOMIC: only changes the bike if it is STILL 'available' at the moment of the update,
    so two riders pressing 'reserve' at the same time can never both get the same bike.
    """
    bike = find_bike(bike_id)
    if bike["type"] == "electric" and (bike["battery_level"] or 0) < MIN_BATTERY:
        raise ApiError(409, f"Bike {bike_id} battery is too low ({bike['battery_level']}%)")
    updated = globals.bikes.find_one_and_update(
        {"bike_id": bike_id, "status": "available"},
        {"$set": {"status": new_status}}, return_document=ReturnDocument.AFTER)
    if updated is None:
        raise ApiError(409, f"Bike {bike_id} is not available (it is {bike['status']})")
    return updated


def find_rental(rental_id):
    check_id(rental_id, "R", "rental")
    rental = globals.rentals.find_one({"rental_id": rental_id}, {"_id": 0})
    if rental is None:
        raise ApiError(404, f"Rental {rental_id} not found")
    if rental["user_id"] != g.user_id and g.role != "admin":
        raise ApiError(403, "This rental belongs to another user")
    return rental


def new_rental(bike, status):
    t = now()
    rental = {
        "rental_id": next_id("rentals", globals.rentals, "rental_id", "R", 5),
        "user_id": g.user_id, "bike_id": bike["bike_id"],
        "start_station_id": bike["station_id"], "end_station_id": None,
        "reserved_at": t if status == "reserved" else None,
        "expires_at": t + timedelta(minutes=RESERVATION_MINUTES) if status == "reserved" else None,
        "start_time": t if status == "active" else None, "end_time": None,
        "distance_km": 0, "duration_min": 0, "total_cost": 0,
        "status": status, "payment": None,
    }
    globals.rentals.insert_one(rental)
    rental.pop("_id", None)
    return rental


# ---------- 1. reserve ----------
@rentals_bp.route("/reservations", methods=["POST"])
@role_required("rider")
def reserve_bike():
    data = get_data()
    require_fields(data, ["bike_id"])
    expire_old_reservations()
    check_no_open_rental(g.user_id)
    bike = grab_bike(str(data["bike_id"]).strip(), "reserved")
    rental = new_rental(bike, "reserved")
    return respond({"message": f"Bike {bike['bike_id']} reserved for {RESERVATION_MINUTES} minutes",
                    "rental": rental}, 201)


@rentals_bp.route("/reservations/<string:rental_id>/cancel", methods=["PATCH"])
@jwt_required
def cancel_reservation(rental_id):
    expire_old_reservations()
    rental = find_rental(rental_id)
    if rental["status"] != "reserved":
        raise ApiError(409, f"Only reserved rentals can be cancelled - this one is {rental['status']}")
    globals.rentals.update_one({"rental_id": rental_id},
                               {"$set": {"status": "cancelled", "cancel_reason": "cancelled_by_user"}})
    globals.bikes.update_one({"bike_id": rental["bike_id"]}, {"$set": {"status": "available"}})
    return respond({"message": "Reservation cancelled", "rental": find_rental(rental_id)}, 200)


# ---------- 2. unlock (start riding) ----------
@rentals_bp.route("/rentals/<string:rental_id>/unlock", methods=["POST"])
@role_required("rider")
def unlock_reserved(rental_id):
    expire_old_reservations()
    rental = find_rental(rental_id)
    if rental["status"] == "cancelled" and rental.get("cancel_reason") == "expired":
        raise ApiError(410, "This reservation has expired - please reserve again")
    if rental["status"] != "reserved":
        raise ApiError(409, f"Only a reserved rental can be unlocked - this one is {rental['status']}")
    globals.bikes.update_one({"bike_id": rental["bike_id"]},
                             {"$set": {"status": "in_use", "station_id": None}})
    globals.rentals.update_one({"rental_id": rental_id},
                               {"$set": {"status": "active", "start_time": now()}})
    return respond({"message": "Bike unlocked - enjoy your ride", "rental": find_rental(rental_id)}, 200)


@rentals_bp.route("/rentals", methods=["POST"])
@role_required("rider")
def walk_up_hire():
    """unlock an available bike straight away, without reserving first"""
    data = get_data()
    require_fields(data, ["bike_id"])
    expire_old_reservations()
    check_no_open_rental(g.user_id)
    bike = grab_bike(str(data["bike_id"]).strip(), "in_use")
    rental = new_rental(bike, "active")
    globals.bikes.update_one({"bike_id": bike["bike_id"]}, {"$set": {"station_id": None}})
    return respond({"message": "Bike unlocked - enjoy your ride", "rental": rental}, 201)


# ---------- 3. return ----------
@rentals_bp.route("/rentals/<string:rental_id>/return", methods=["POST"])
@role_required("rider")
def return_bike(rental_id):
    data = get_data()
    require_fields(data, ["end_station_id"])
    end_id = check_id(str(data["end_station_id"]).strip(), "ST", "station")
    rental = find_rental(rental_id)
    if rental["status"] != "active":
        raise ApiError(409, f"Only an active rental can be returned - this one is {rental['status']}")
    end_station = globals.stations.find_one({"station_id": end_id})
    if end_station is None:
        raise ApiError(404, f"Station {end_id} not found")

    # station full? refuse and suggest the 3 closest stations with a free dock
    docked = globals.bikes.count_documents({"station_id": end_id})
    if docked >= end_station["total_docks"]:
        lng, lat = end_station["location"]["coordinates"]
        nearby = list(globals.stations.aggregate([
            {"$geoNear": {"near": {"type": "Point", "coordinates": [lng, lat]},
                          "distanceField": "distance_m", "maxDistance": 3000, "spherical": True}},
            {"$lookup": {"from": "bikes", "localField": "station_id", "foreignField": "station_id", "as": "d"}},
            {"$project": {"_id": 0, "station_id": 1, "name": 1, "distance_m": 1,
                          "free_docks": {"$subtract": ["$total_docks", {"$size": "$d"}]}}},
            {"$match": {"free_docks": {"$gt": 0}}},
            {"$limit": 3}]))
        for s in nearby:
            s["distance_m"] = round(s["distance_m"])
        return respond({"error": f"Station {end_id} is full - please return to another station",
                        "status": 409, "suggested_stations": nearby}, 409)

    bike = find_bike(rental["bike_id"])
    start_station = globals.stations.find_one({"station_id": rental["start_station_id"]})
    end_time = now()
    minutes = max(1, math.ceil((end_time - rental["start_time"]).total_seconds() / 60))
    a = start_station["location"]["coordinates"]
    b = end_station["location"]["coordinates"]
    distance = round(haversine_km(a[1], a[0], b[1], b[0]), 2)
    cost = calculate_cost(bike["type"], minutes, start_station["zone"])

    globals.rentals.update_one({"rental_id": rental_id}, {"$set": {
        "status": "completed", "end_station_id": end_id, "end_time": end_time,
        "duration_min": minutes, "distance_km": distance, "total_cost": cost,
        "payment": {"status": "unpaid", "amount": cost, "currency": "GBP"}}})

    bike_changes = {"station_id": end_id, "status": "available"}
    if bike["type"] == "electric":
        bike_changes["battery_level"] = max(0, bike["battery_level"] - math.ceil(distance * 3))
    globals.bikes.update_one({"bike_id": bike["bike_id"]}, {"$set": bike_changes})

    return respond({"message": f"Ride complete - {minutes} min, {distance} km, £{cost:.2f}",
                    "rental": find_rental(rental_id)}, 200)


# ---------- viewing ----------
@rentals_bp.route("/rentals/current", methods=["GET"])
@jwt_required
def my_current_rental():
    expire_old_reservations()
    rental = globals.rentals.find_one({"user_id": g.user_id, "status": {"$in": ["reserved", "active"]}},
                                      {"_id": 0})
    if rental is None:
        raise ApiError(404, "You have no reservation or ride in progress")
    if rental["status"] == "reserved":
        rental["seconds_left"] = max(0, int((rental["expires_at"] - now()).total_seconds()))
    return respond(rental, 200)


@rentals_bp.route("/rentals/history", methods=["GET"])
@jwt_required
def my_history():
    """my past rides + station names ($lookup) + totals - all in ONE query with $facet"""
    page_num, page_size, page_start = get_pagination()
    result = list(globals.rentals.aggregate([
        {"$match": {"user_id": g.user_id}},
        {"$facet": {
            "data": [
                {"$sort": {"rental_id": -1}}, {"$skip": page_start}, {"$limit": page_size},
                {"$lookup": {"from": "stations", "localField": "start_station_id",
                             "foreignField": "station_id", "as": "from"}},
                {"$lookup": {"from": "stations", "localField": "end_station_id",
                             "foreignField": "station_id", "as": "to"}},
                {"$addFields": {"from_name": {"$arrayElemAt": ["$from.name", 0]},
                                "to_name": {"$arrayElemAt": ["$to.name", 0]}}},
                {"$project": {"_id": 0, "from": 0, "to": 0}},
            ],
            "total": [{"$count": "count"}],
            "summary": [
                {"$match": {"status": "completed"}},
                {"$group": {"_id": None, "rides": {"$sum": 1}, "spent": {"$sum": "$total_cost"},
                            "km": {"$sum": "$distance_km"}}},
            ],
        }},
    ]))[0]
    total = result["total"][0]["count"] if result["total"] else 0
    body = paged_response(result["data"], total, page_num, page_size)
    s = result["summary"][0] if result["summary"] else {"rides": 0, "spent": 0, "km": 0}
    body["summary"] = {"completed_rides": s["rides"], "total_spent": round(s["spent"], 2),
                       "total_km": round(s["km"], 2)}
    return respond(body, 200)


@rentals_bp.route("/rentals/<string:rental_id>", methods=["GET"])
@jwt_required
def get_one_rental(rental_id):
    expire_old_reservations()
    return respond(find_rental(rental_id), 200)
