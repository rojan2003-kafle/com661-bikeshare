from datetime import timedelta
from flask import Blueprint, request
import globals
from decorators import role_required
from utils import ApiError, respond, parse_int, parse_enum, now
from blueprints.stations.stations import availability_stages
from blueprints.rentals.rentals import haversine_km

admin_bp = Blueprint("admin_bp", __name__)

WEEKDAYS = {1: "Sunday", 2: "Monday", 3: "Tuesday", 4: "Wednesday",
            5: "Thursday", 6: "Friday", 7: "Saturday"}


def since():
    """?days=30 -> only look at the last 30 days"""
    days = parse_int(request.args.get("days", 90), "days", 1, 3650)
    return now() - timedelta(days=days), days


def station_names():
    return {s["station_id"]: s["name"] for s in globals.stations.find({}, {"station_id": 1, "name": 1})}


# ---------------- REVENUE ----------------
@admin_bp.route("/admin/revenue", methods=["GET"])
@role_required("admin")
def revenue():
    """/admin/revenue?group_by=day|month&days=90"""
    group_by = parse_enum(request.args.get("group_by", "month"), "group_by", ["day", "month"])
    fmt = "%Y-%m-%d" if group_by == "day" else "%Y-%m"
    start, days = since()

    result = list(globals.rentals.aggregate([
        {"$match": {"payment.status": "succeeded", "payment.paid_at": {"$gte": start}}},
        # join the bike (for its type) and the start station (for its zone)
        {"$lookup": {"from": "bikes", "localField": "bike_id", "foreignField": "bike_id", "as": "bike"}},
        {"$lookup": {"from": "stations", "localField": "start_station_id",
                     "foreignField": "station_id", "as": "station"}},
        {"$addFields": {"bike_type": {"$arrayElemAt": ["$bike.type", 0]},
                        "zone": {"$arrayElemAt": ["$station.zone", 0]}}},
        # $facet = several reports from ONE query
        {"$facet": {
            "totals": [{"$group": {"_id": None, "revenue": {"$sum": "$payment.amount"},
                                   "payments": {"$sum": 1}, "avg": {"$avg": "$payment.amount"}}}],
            "by_period": [{"$group": {"_id": {"$dateToString": {"format": fmt, "date": "$payment.paid_at"}},
                                      "revenue": {"$sum": "$payment.amount"}, "rides": {"$sum": 1}}},
                          {"$sort": {"_id": 1}}],
            "by_bike_type": [{"$group": {"_id": "$bike_type", "revenue": {"$sum": "$payment.amount"},
                                         "rides": {"$sum": 1}}}, {"$sort": {"revenue": -1}}],
            "by_zone": [{"$group": {"_id": "$zone", "revenue": {"$sum": "$payment.amount"},
                                    "rides": {"$sum": 1}}}, {"$sort": {"revenue": -1}}],
        }},
    ]))[0]

    t = result["totals"][0] if result["totals"] else {"revenue": 0, "payments": 0, "avg": 0}
    rows = lambda items, key: [{key: x["_id"], "revenue": round(x["revenue"], 2), "rides": x["rides"]}
                               for x in items]
    return respond({"days": days, "currency": "GBP",
                    "total_revenue": round(t["revenue"], 2), "payments": t["payments"],
                    "average_payment": round(t["avg"] or 0, 2),
                    "by_" + group_by: rows(result["by_period"], group_by),
                    "by_bike_type": rows(result["by_bike_type"], "bike_type"),
                    "by_zone": rows(result["by_zone"], "zone")}, 200)


# ---------------- ANALYTICS: peak hours, weekdays, popular routes ----------------
@admin_bp.route("/admin/analytics", methods=["GET"])
@role_required("admin")
def analytics():
    start, days = since()
    result = list(globals.rentals.aggregate([
        {"$match": {"status": "completed", "start_time": {"$gte": start}}},
        {"$facet": {
            "hours": [{"$group": {"_id": {"$hour": "$start_time"}, "rides": {"$sum": 1}}},
                      {"$sort": {"_id": 1}}],
            "weekdays": [{"$group": {"_id": {"$dayOfWeek": "$start_time"}, "rides": {"$sum": 1}}},
                         {"$sort": {"_id": 1}}],
            "routes": [
                {"$match": {"$expr": {"$ne": ["$start_station_id", "$end_station_id"]}}},
                {"$group": {"_id": {"from": "$start_station_id", "to": "$end_station_id"},
                            "rides": {"$sum": 1}, "avg_minutes": {"$avg": "$duration_min"}}},
                {"$sort": {"rides": -1}}, {"$limit": 10}],
        }},
    ]))[0]
    names = station_names()
    hours = [{"hour": f"{x['_id']:02d}:00", "rides": x["rides"]} for x in result["hours"]]
    return respond({
        "days": days,
        "busiest_hour": max(hours, key=lambda h: h["rides"]) if hours else None,
        "rides_by_hour": hours,
        "rides_by_weekday": [{"day": WEEKDAYS[x["_id"]], "rides": x["rides"]} for x in result["weekdays"]],
        "popular_routes": [{"from": names.get(x["_id"]["from"]), "to": names.get(x["_id"]["to"]),
                            "rides": x["rides"], "avg_minutes": round(x["avg_minutes"], 1)}
                           for x in result["routes"]],
    }, 200)


# ---------------- REBALANCING ----------------
@admin_bp.route("/admin/rebalancing", methods=["GET"])
@role_required("admin")
def rebalancing():
    """
    Stations under ?low=20% full need bikes, stations over ?high=85% have too many.
    Pair each overfull station with the NEAREST under-full one and suggest how many bikes to move.
    """
    low = parse_int(request.args.get("low", 20), "low", 0, 50)
    high = parse_int(request.args.get("high", 85), "high", 50, 100)
    stations = list(globals.stations.aggregate([{"$match": {}}] + availability_stages()))
    for s in stations:
        s["occupancy_pct"] = round(100 * s["bikes_docked"] / s["total_docks"], 1)
    empty = [s for s in stations if s["occupancy_pct"] <= low]
    full = sorted([s for s in stations if s["occupancy_pct"] >= high], key=lambda s: -s["occupancy_pct"])

    spare = {s["station_id"]: s["bikes_available"] - s["total_docks"] // 2 for s in full}
    need = {s["station_id"]: s["total_docks"] // 2 - s["bikes_docked"] for s in empty}
    moves = []
    for src in full:
        lng1, lat1 = src["location"]["coordinates"]
        for dst in sorted(empty, key=lambda d: haversine_km(lat1, lng1, d["location"]["coordinates"][1],
                                                            d["location"]["coordinates"][0])):
            qty = min(spare[src["station_id"]], need[dst["station_id"]])
            if qty <= 0:
                continue
            lng2, lat2 = dst["location"]["coordinates"]
            moves.append({"from": src["name"], "to": dst["name"], "bikes": qty,
                          "distance_km": round(haversine_km(lat1, lng1, lat2, lng2), 2)})
            spare[src["station_id"]] -= qty
            need[dst["station_id"]] -= qty
            if spare[src["station_id"]] <= 0:
                break

    short = lambda s: {k: s[k] for k in ["station_id", "name", "total_docks", "bikes_docked",
                                          "free_docks", "occupancy_pct"]}
    return respond({"nearly_empty": [short(s) for s in empty],
                    "nearly_full": [short(s) for s in full],
                    "suggested_moves": moves,
                    "bikes_to_move": sum(m["bikes"] for m in moves)}, 200)


# ---------------- REPEAT FAULTS ----------------
@admin_bp.route("/admin/repeat-faults", methods=["GET"])
@role_required("admin", "mechanic")
def repeat_faults():
    """bikes with ?min_reports=3 or more faults in the last ?days=90"""
    min_reports = parse_int(request.args.get("min_reports", 3), "min_reports", 2, 50)
    start, days = since()
    result = list(globals.maintenance.aggregate([
        {"$match": {"created_at": {"$gte": start}}},
        {"$group": {"_id": "$bike_id", "reports": {"$sum": 1},
                    "issues": {"$push": "$issue_type"}, "last_reported": {"$max": "$created_at"}}},
        {"$match": {"reports": {"$gte": min_reports}}},
        {"$sort": {"reports": -1}},
        {"$project": {"_id": 0, "bike_id": "$_id", "reports": 1, "issues": 1, "last_reported": 1}},
    ]))
    for r in result:
        r["recommendation"] = "consider retiring" if r["reports"] >= 5 else "full inspection"
    return respond({"days": days, "count": len(result), "bikes": result}, 200)
