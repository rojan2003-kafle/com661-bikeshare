import re
from flask import Blueprint, request
import globals
from utils import (ApiError, respond, parse_int, parse_float, parse_enum, check_id,
                   get_pagination, paged_response)

stations_bp = Blueprint("stations_bp", __name__)

ZONES = ["central", "inner", "outer"]
MIN_BATTERY = 20     # electric bikes below 20% can't be hired


def availability_stages():
    """
    Aggregation stages that JOIN each station to the bikes docked there ($lookup)
    and work out live numbers. A bike counts as available if its status is
    'available' and (for electric bikes) the battery is at least MIN_BATTERY.
    """
    usable = {"$and": [
        {"$eq": ["$$b.status", "available"]},
        {"$or": [{"$eq": ["$$b.type", "standard"]},
                 {"$gte": ["$$b.battery_level", MIN_BATTERY]}]},
    ]}
    return [
        {"$lookup": {"from": "bikes", "localField": "station_id",
                     "foreignField": "station_id", "as": "docked"}},
        {"$addFields": {
            "bikes_docked": {"$size": "$docked"},
            "bikes_available": {"$size": {"$filter": {"input": "$docked", "as": "b", "cond": usable}}},
        }},
        {"$addFields": {"free_docks": {"$subtract": ["$total_docks", "$bikes_docked"]}}},
        {"$project": {"_id": 0, "docked": 0}},
    ]


# ---------------- GET all stations (filter, search, paginate) ----------------
@stations_bp.route("/stations", methods=["GET"])
def show_all_stations():
    page_num, page_size, page_start = get_pagination()

    match = {}
    if request.args.get("zone"):
        match["zone"] = parse_enum(request.args["zone"], "zone", ZONES)
    if request.args.get("search"):
        text = re.escape(request.args["search"].strip())
        match["$or"] = [{"name": {"$regex": text, "$options": "i"}},
                        {"address": {"$regex": text, "$options": "i"}}]

    pipeline = [{"$match": match}] + availability_stages()
    if request.args.get("min_bikes"):
        pipeline.append({"$match": {"bikes_available":
                         {"$gte": parse_int(request.args["min_bikes"], "min_bikes", 0, 100)}}})

    # $facet = run two pipelines at once: one page of data + the total count
    pipeline.append({"$facet": {
        "data": [{"$sort": {"name": 1}}, {"$skip": page_start}, {"$limit": page_size}],
        "total": [{"$count": "count"}],
    }})
    result = list(globals.stations.aggregate(pipeline))[0]
    total = result["total"][0]["count"] if result["total"] else 0
    return respond(paged_response(result["data"], total, page_num, page_size), 200)


# ---------------- GEO: stations near me ----------------
@stations_bp.route("/stations/nearby", methods=["GET"])
def nearby_stations():
    """ /stations/nearby?lat=51.5033&lng=-0.1145&radius=800&min_bikes=1 """
    if not request.args.get("lat") or not request.args.get("lng"):
        raise ApiError(400, "Query parameters 'lat' and 'lng' are required")
    lat = parse_float(request.args["lat"], "lat", -90, 90)
    lng = parse_float(request.args["lng"], "lng", -180, 180)
    radius = parse_int(request.args.get("radius", 1000), "radius", 50, 20000)   # metres
    min_bikes = parse_int(request.args.get("min_bikes", 0), "min_bikes", 0, 100)

    pipeline = [
        # $geoNear MUST be the first stage and needs the 2dsphere index
        {"$geoNear": {
            "near": {"type": "Point", "coordinates": [lng, lat]},   # GeoJSON = [lng, lat]
            "distanceField": "distance_m",
            "maxDistance": radius,
            "spherical": True,
        }},
    ] + availability_stages() + [
        {"$match": {"bikes_available": {"$gte": min_bikes}}},
        {"$limit": 10},
    ]
    results = list(globals.stations.aggregate(pipeline))
    for s in results:
        s["distance_m"] = round(s["distance_m"])
        s["walking_minutes"] = max(1, round(s["distance_m"] / 80))   # ~80 m per minute
    return respond({"count": len(results), "stations": results}, 200)


# ---------------- GET one station ----------------
@stations_bp.route("/stations/<string:station_id>", methods=["GET"])
def show_one_station(station_id):
    check_id(station_id, "ST", "station")
    result = list(globals.stations.aggregate(
        [{"$match": {"station_id": station_id}}] + availability_stages()))
    if not result:
        raise ApiError(404, f"Station {station_id} not found")
    station = result[0]
    station["available_bikes"] = list(globals.bikes.find(
        {"station_id": station_id, "status": "available"},
        {"_id": 0, "bike_id": 1, "type": 1, "battery_level": 1}))
    return respond(station, 200)


# ================= ADMIN: create / update / delete =================
from decorators import role_required
from utils import get_data, require_fields, parse_str, next_id


def read_station_fields(data, partial=False):
    """validate the body; partial=True for PUT (only send what you change)"""
    if not partial:
        require_fields(data, ["name", "address", "lat", "lng", "total_docks", "zone"])
    fields = {}
    if "name" in data:
        fields["name"] = parse_str(data["name"], "name", 3, 100)
    if "address" in data:
        fields["address"] = parse_str(data["address"], "address", 5, 200)
    if "lat" in data or "lng" in data:
        lat = parse_float(data.get("lat"), "lat", 51.25, 51.75)    # Greater London only
        lng = parse_float(data.get("lng"), "lng", -0.55, 0.35)
        fields["location"] = {"type": "Point", "coordinates": [lng, lat]}
    if "total_docks" in data:
        fields["total_docks"] = parse_int(data["total_docks"], "total_docks", 1, 100)
    if "zone" in data:
        fields["zone"] = parse_enum(data["zone"], "zone", ZONES)
    return fields


@stations_bp.route("/stations", methods=["POST"])
@role_required("admin")
def add_station():
    fields = read_station_fields(get_data())
    fields["station_id"] = next_id("stations", globals.stations, "station_id", "ST", 3)
    globals.stations.insert_one(fields)
    fields.pop("_id", None)
    return respond({"message": "Station created",
                    "url": request.host_url + "api/v1.0/stations/" + fields["station_id"],
                    "station": fields}, 201)


@stations_bp.route("/stations/<string:station_id>", methods=["PUT"])
@role_required("admin")
def edit_station(station_id):
    check_id(station_id, "ST", "station")
    fields = read_station_fields(get_data(), partial=True)
    if not fields:
        raise ApiError(400, "Nothing to update - send at least one field")
    if "total_docks" in fields:
        docked = globals.bikes.count_documents({"station_id": station_id})
        if fields["total_docks"] < docked:
            raise ApiError(409, f"{docked} bikes are docked here - total_docks can't be lower than that")
    result = globals.stations.update_one({"station_id": station_id}, {"$set": fields})
    if result.matched_count == 0:
        raise ApiError(404, f"Station {station_id} not found")
    return respond({"message": "Station updated",
                    "url": request.host_url + "api/v1.0/stations/" + station_id}, 200)


@stations_bp.route("/stations/<string:station_id>", methods=["DELETE"])
@role_required("admin")
def delete_station(station_id):
    check_id(station_id, "ST", "station")
    docked = globals.bikes.count_documents({"station_id": station_id})
    if docked:
        raise ApiError(409, f"Cannot delete - {docked} bike(s) still docked here. Move them first.")
    result = globals.stations.delete_one({"station_id": station_id})
    if result.deleted_count == 0:
        raise ApiError(404, f"Station {station_id} not found")
    return respond({}, 204)
