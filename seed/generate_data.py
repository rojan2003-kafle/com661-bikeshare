"""
Generates the Smart Bike Sharing & Maintenance dataset (London) as JSON files
ready for mongoimport --jsonArray.

Collections: users, stations, bikes, rentals, maintenance_reports
All cross-references (station_id, bike_id, user_id) are consistent:
  - in_use bikes have station_id = null and exactly one 'active' rental
  - reserved bikes have exactly one 'reserved' rental
  - under_repair bikes have an open / in_progress maintenance report
  - bikes docked at a station never exceed that station's total_docks
"""
import json, math, random, datetime as dt
import bcrypt

random.seed(661)
NOW = dt.datetime(2026, 10, 19, 13, 45, 0)          # UTC
import os
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

def oid():
    return {"$oid": "%024x" % random.getrandbits(96)}

def iso(d):  # MongoDB extended JSON date
    return {"$date": d.strftime("%Y-%m-%dT%H:%M:%SZ")} if d else None

def haversine(lat1, lng1, lat2, lng2):
    r = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))

# ---------------------------------------------------------------- stations
# (area, postcode, lat, lng) - approximate real centre points of London areas
AREAS = [
    ("Waterloo", "SE1", 51.5033, -0.1145), ("Southwark", "SE1", 51.5045, -0.1050),
    ("London Bridge", "SE1", 51.5055, -0.0865), ("Bankside", "SE1", 51.5075, -0.0990),
    ("Covent Garden", "WC2", 51.5117, -0.1240), ("Soho", "W1", 51.5136, -0.1365),
    ("Holborn", "WC1", 51.5174, -0.1200), ("Bloomsbury", "WC1", 51.5220, -0.1260),
    ("Fitzrovia", "W1", 51.5190, -0.1380), ("Marylebone", "W1", 51.5200, -0.1530),
    ("Mayfair", "W1", 51.5100, -0.1480), ("Westminster", "SW1", 51.4995, -0.1350),
    ("Victoria", "SW1", 51.4965, -0.1440), ("Pimlico", "SW1", 51.4890, -0.1340),
    ("Farringdon", "EC1", 51.5203, -0.1050), ("Clerkenwell", "EC1", 51.5240, -0.1060),
    ("Barbican", "EC2", 51.5200, -0.0940), ("Moorgate", "EC2", 51.5186, -0.0886),
    ("Liverpool Street", "EC2", 51.5178, -0.0823), ("Aldgate", "EC3", 51.5143, -0.0755),
    ("Tower Hill", "EC3", 51.5098, -0.0766), ("St Paul's", "EC4", 51.5138, -0.0984),
    ("King's Cross", "N1", 51.5308, -0.1238), ("Euston", "NW1", 51.5282, -0.1337),
    ("Camden Town", "NW1", 51.5390, -0.1426), ("Islington", "N1", 51.5362, -0.1033),
    ("Angel", "N1", 51.5322, -0.1058), ("Shoreditch", "E1", 51.5265, -0.0780),
    ("Hoxton", "N1", 51.5310, -0.0810), ("Whitechapel", "E1", 51.5195, -0.0596),
    ("Bethnal Green", "E2", 51.5270, -0.0550), ("Hackney", "E8", 51.5450, -0.0553),
    ("Kensington", "W8", 51.5010, -0.1920), ("South Kensington", "SW7", 51.4941, -0.1738),
    ("Chelsea", "SW3", 51.4875, -0.1687), ("Knightsbridge", "SW1", 51.5015, -0.1607),
    ("Paddington", "W2", 51.5154, -0.1755), ("Notting Hill", "W11", 51.5090, -0.1960),
    ("Battersea", "SW11", 51.4790, -0.1500), ("Vauxhall", "SE11", 51.4861, -0.1253),
    ("Kennington", "SE11", 51.4882, -0.1050), ("Elephant & Castle", "SE1", 51.4946, -0.1001),
    ("Bermondsey", "SE1", 51.4980, -0.0640), ("Canary Wharf", "E14", 51.5054, -0.0235),
    ("Limehouse", "E14", 51.5123, -0.0397), ("Stratford", "E15", 51.5416, -0.0033),
    ("Brixton", "SW9", 51.4613, -0.1156), ("Clapham", "SW4", 51.4618, -0.1384),
    ("Fulham", "SW6", 51.4730, -0.2010), ("Hammersmith", "W6", 51.4927, -0.2240),
    ("Shepherd's Bush", "W12", 51.5046, -0.2187), ("Wandsworth", "SW18", 51.4567, -0.1910),
    ("Greenwich", "SE10", 51.4826, -0.0077), ("Peckham", "SE15", 51.4740, -0.0690),
]
STREETS = ["Road", "Street", "Square", "Lane", "Place", "Gardens", "Walk", "Row"]
PREFIX = ["High", "Church", "Station", "Park", "Mill", "Queen's", "King's", "Victoria",
          "Albert", "Market", "Bridge", "Grove", "Chapel", "Union", "Wharf", "Garden"]
CHARING_CROSS = (51.5073, -0.1276)

stations, used = [], set()
for i in range(120):
    area, pc, lat, lng = AREAS[i % len(AREAS)]
    while True:
        street = f"{random.choice(PREFIX)} {random.choice(STREETS)}"
        if (street, area) not in used:
            used.add((street, area)); break
    lat = round(lat + random.uniform(-0.0045, 0.0045), 6)
    lng = round(lng + random.uniform(-0.0065, 0.0065), 6)
    d = haversine(lat, lng, *CHARING_CROSS)
    zone = "central" if d < 3 else "inner" if d < 6.5 else "outer"
    stations.append({
        "station_id": f"ST{i+1:03d}",
        "name": f"{street}, {area}",
        "address": f"{random.randint(1, 220)} {street}, {area}, London {pc} {random.randint(1,9)}{random.choice('ABDEFGHJLNPQRSTUWXYZ')}{random.choice('ABDEFGHJLNPQRSTUWXYZ')}",
        "location": {"type": "Point", "coordinates": [lng, lat]},   # GeoJSON: [lng, lat]
        "total_docks": random.choice([10, 12, 15, 16, 18, 20, 24]),
        "zone": zone,
    })
st_by_id = {s["station_id"]: s for s in stations}

# ---------------------------------------------------------------- users
FIRST = ["Oliver", "Amelia", "George", "Isla", "Harry", "Ava", "Noah", "Mia", "Jack", "Ivy",
         "Leo", "Grace", "Arthur", "Freya", "Muhammad", "Lily", "Oscar", "Sophia", "Charlie",
         "Emily", "Theo", "Ella", "Henry", "Rosie", "Aarav", "Priya", "Rojan", "Sita", "Kwame",
         "Amara", "Liam", "Chloe", "Ethan", "Zara", "Daniel", "Hannah", "Samuel", "Aisha",
         "Lucas", "Maya", "Finn", "Nadia", "Ryan", "Erin", "Tomasz", "Ewa", "Diego", "Lucia"]
LAST = ["Smith", "Jones", "Taylor", "Brown", "Williams", "Wilson", "Johnson", "Davies",
        "Patel", "Khan", "Robinson", "Wright", "Thompson", "Evans", "Walker", "White",
        "Roberts", "Green", "Hall", "Wood", "Clarke", "Shah", "Ahmed", "Murphy", "Kelly",
        "Nowak", "Okafor", "Mensah", "Garcia", "Rossi", "Kafle", "Gurung", "Singh", "Lewis"]
PASSWORDS = {"rider": "Rider123!", "mechanic": "Mechanic123!", "admin": "Admin123!"}
roles = ["admin"] * 5 + ["mechanic"] * 15 + ["rider"] * 130
users, emails = [], set()
for i, role in enumerate(roles):
    fn, ln = random.choice(FIRST), random.choice(LAST)
    base = f"{fn}.{ln}".lower()
    email, n = f"{base}@example.com", 1
    while email in emails:
        n += 1; email = f"{base}{n}@example.com"
    emails.add(email)
    created = NOW - dt.timedelta(days=random.randint(90, 720), minutes=random.randint(0, 1440))
    users.append({
        "user_id": f"U{i+1:03d}",
        "name": f"{fn} {ln}",
        "email": email,
        "password_hash": bcrypt.hashpw(PASSWORDS[role].encode(), bcrypt.gensalt(rounds=10)).decode(),
        "role": role,
        "created_at": created,
    })
# fixed, easy-to-remember accounts for testing / Postman
for u, (name, email) in zip([users[0], users[5], users[20]],
                            [("Admin Demo", "admin@bikeshare.test"),
                             ("Mechanic Demo", "mechanic@bikeshare.test"),
                             ("Rider Demo", "rider@bikeshare.test")]):
    u["name"], u["email"] = name, email
riders = [u for u in users if u["role"] == "rider"]
mechanics = [u for u in users if u["role"] == "mechanic"]

# ---------------------------------------------------------------- bikes
bikes = []
for i in range(900):
    btype = "electric" if random.random() < 0.35 else "standard"
    bikes.append({"bike_id": f"BK{i+1:04d}", "station_id": None, "type": btype,
                  "battery_level": random.randint(15, 100) if btype == "electric" else None,
                  "status": "available"})
random.shuffle(bikes)
statuses = ["in_use"] * 45 + ["reserved"] * 12 + ["under_repair"] * 55
for b, s in zip(bikes, statuses):
    b["status"] = s
# dock all non-in_use bikes, respecting capacity; leave a few stations empty / full
capacity = {s["station_id"]: s["total_docks"] for s in stations}
empty = set(random.sample(list(capacity), 6))
full = set(random.sample([k for k in capacity if k not in empty], 6))
docked = {k: 0 for k in capacity}
for sid in full:                                  # fill these stations to the brim
    for b in bikes:
        if docked[sid] >= capacity[sid]: break
        if b["status"] != "in_use" and b["station_id"] is None:
            b["station_id"] = sid; docked[sid] += 1
for b in bikes:
    if b["status"] == "in_use" or b["station_id"]: continue
    choices = [k for k in capacity if k not in empty and k not in full and docked[k] < capacity[k] - 2]
    sid = random.choice(choices)
    b["station_id"] = sid; docked[sid] += 1
for b in bikes:                                   # electric bikes under 20% are flagged low
    if b["type"] == "electric" and b["status"] == "in_use":
        b["battery_level"] = random.randint(30, 95)
bikes.sort(key=lambda b: b["bike_id"])
bike_by_id = {b["bike_id"]: b for b in bikes}

# ---------------------------------------------------------------- rentals
PRICING = {"standard": {"unlock": 1.00, "per_min": 0.05},
           "electric": {"unlock": 1.00, "per_min": 0.20}}
ZONE_MULT = {"central": 1.0, "inner": 1.0, "outer": 0.9}
HOUR_WEIGHTS = [1, 1, 1, 1, 1, 2, 5, 14, 22, 12, 6, 6, 9, 8, 6, 7, 11, 22, 18, 10, 7, 5, 3, 2]

def price(btype, mins, zone):
    p = PRICING[btype]
    return round((p["unlock"] + p["per_min"] * mins) * ZONE_MULT[zone], 2)

# popular routes: commuter pairs ridden repeatedly
popular = [tuple(random.sample(stations, 2)) for _ in range(15)]
rentals = []
def new_id(): return f"R{len(rentals)+1:05d}"

for _ in range(1500):
    bike = random.choice(bikes)
    if random.random() < 0.25:
        a, b = random.choice(popular)
    else:
        a = random.choice(stations)
        near = sorted(stations, key=lambda s: haversine(*a["location"]["coordinates"][::-1],
                                                         *s["location"]["coordinates"][::-1]))[1:25]
        b = random.choice(near)
    day = NOW - dt.timedelta(days=random.randint(1, 80))
    hour = random.choices(range(24), weights=HOUR_WEIGHTS)[0]
    start = day.replace(hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59))
    dist = haversine(*a["location"]["coordinates"][::-1], *b["location"]["coordinates"][::-1]) * 1.3
    dist = round(max(dist, 0.4) + random.uniform(0, 0.6), 2)
    speed = 17 if bike["type"] == "electric" else 12            # km/h
    mins = max(3, round(dist / speed * 60 + random.uniform(1, 6)))
    end = start + dt.timedelta(minutes=mins)
    rider = random.choice(riders)
    if random.random() < 0.05:   # cancelled reservation
        reserved_at = start - dt.timedelta(minutes=random.randint(2, 9))
        rentals.append({"rental_id": new_id(), "user_id": rider["user_id"], "bike_id": bike["bike_id"],
                        "start_station_id": a["station_id"], "end_station_id": None,
                        "reserved_at": reserved_at, "expires_at": reserved_at + dt.timedelta(minutes=10),
                        "start_time": None, "end_time": None, "distance_km": 0, "duration_min": 0,
                        "total_cost": 0, "status": "cancelled", "payment": None})
        continue
    cost = price(bike["type"], mins, a["zone"])
    paid = random.random() < 0.96
    rentals.append({
        "rental_id": new_id(), "user_id": rider["user_id"], "bike_id": bike["bike_id"],
        "start_station_id": a["station_id"], "end_station_id": b["station_id"],
        "reserved_at": start - dt.timedelta(minutes=random.randint(1, 8)) if random.random() < 0.4 else None,
        "expires_at": None,
        "start_time": start, "end_time": end, "distance_km": dist, "duration_min": mins,
        "total_cost": cost, "status": "completed",
        "payment": {   # embedded sub-document
            "payment_id": f"pi_test_{random.getrandbits(64):016x}",
            "amount": cost, "currency": "GBP", "method": "card",
            "card_brand": random.choice(["visa", "mastercard", "amex"]),
            "card_last4": random.choice(["4242", "4444", "0005", "5556"]),
            "status": "succeeded" if paid else "pending",
            "paid_at": end + dt.timedelta(seconds=random.randint(5, 90)) if paid else None,
        },
    })
for r in rentals[:]:  # make reserved_at None consistent for rides with no reservation
    if r["status"] == "completed" and r["reserved_at"] is None:
        r["expires_at"] = None
    elif r["status"] == "completed":
        r["expires_at"] = r["reserved_at"] + dt.timedelta(minutes=10)

# current active rides & live reservations, one per rider, matching bike status
free_riders = random.sample(riders, 57)
for bike in [b for b in bikes if b["status"] == "in_use"]:
    rider = free_riders.pop()
    a = random.choice(stations)
    start = NOW - dt.timedelta(minutes=random.randint(2, 40))
    rentals.append({"rental_id": new_id(), "user_id": rider["user_id"], "bike_id": bike["bike_id"],
                    "start_station_id": a["station_id"], "end_station_id": None,
                    "reserved_at": None, "expires_at": None, "start_time": start, "end_time": None,
                    "distance_km": 0, "duration_min": 0, "total_cost": 0, "status": "active", "payment": None})
for bike in [b for b in bikes if b["status"] == "reserved"]:
    rider = free_riders.pop()
    reserved_at = NOW - dt.timedelta(minutes=random.randint(0, 4))
    rentals.append({"rental_id": new_id(), "user_id": rider["user_id"], "bike_id": bike["bike_id"],
                    "start_station_id": bike["station_id"], "end_station_id": None,
                    "reserved_at": reserved_at, "expires_at": reserved_at + dt.timedelta(minutes=10),
                    "start_time": None, "end_time": None, "distance_km": 0, "duration_min": 0,
                    "total_cost": 0, "status": "reserved", "payment": None})

# ---------------------------------------------------------------- maintenance reports
ISSUES = {
    "brakes": ["Front brake feels spongy", "Rear brake not gripping", "Brake lever loose", "Brakes squeal loudly"],
    "tyre": ["Front tyre flat", "Rear tyre puncture", "Tyre worn down to the tread", "Slow leak in rear tyre"],
    "chain": ["Chain keeps slipping", "Chain came off", "Chain rusty and noisy", "Gears skipping"],
    "battery": ["Battery drains very quickly", "Battery won't charge", "Motor cuts out on hills", "Display shows battery error"],
    "other": ["Saddle won't adjust", "Bell missing", "Front light not working", "Basket bent", "Dock lock stuck"],
}
MECH_NOTES = ["Inspected bike at station", "Ordered replacement part", "Replaced part and tested",
              "Adjusted and road tested", "Cleaned and lubricated", "Safety check passed"]
reports = []
def add_report(bike, status, created):
    itype = "battery" if bike["type"] == "electric" and random.random() < 0.4 else \
            random.choice(["brakes", "tyre", "chain", "other"])
    reporter = random.choice(riders + mechanics[:3])
    mech = random.choice(mechanics)
    notes, resolved = [], None
    if status in ("in_progress", "resolved"):
        t = created + dt.timedelta(hours=random.randint(1, 20))
        notes.append({"_id": oid(), "mechanic_id": mech["user_id"], "note": MECH_NOTES[0], "created_at": t})
        if random.random() < 0.5:
            t += dt.timedelta(hours=random.randint(1, 24))
            notes.append({"_id": oid(), "mechanic_id": mech["user_id"], "note": MECH_NOTES[1], "created_at": t})
        if status == "resolved":
            resolved = t + dt.timedelta(hours=random.randint(1, 30))
            notes.append({"_id": oid(), "mechanic_id": mech["user_id"], "note": random.choice(MECH_NOTES[2:]), "created_at": resolved})
    reports.append({
        "report_id": f"MR{len(reports)+1:04d}", "bike_id": bike["bike_id"],
        "reported_by": reporter["user_id"], "issue_type": itype,
        "description": random.choice(ISSUES[itype]),
        "status": status,
        "assigned_to": mech["user_id"] if status != "open" else None,
        "created_at": created, "resolved_at": resolved,
        "notes": notes,   # embedded sub-documents
    })

for b in [b for b in bikes if b["status"] == "under_repair"]:     # live faults
    add_report(b, random.choice(["open", "open", "in_progress"]),
               NOW - dt.timedelta(hours=random.randint(2, 96)))
repeat_offenders = random.sample([b for b in bikes if b["status"] == "available"], 12)
for b in repeat_offenders:                                         # repeated faults
    for _ in range(random.randint(3, 5)):
        add_report(b, "resolved", NOW - dt.timedelta(days=random.randint(5, 85)))
while len(reports) < 220:                                          # one-off historic faults
    b = random.choice([b for b in bikes if b["status"] != "under_repair"])
    add_report(b, "resolved", NOW - dt.timedelta(days=random.randint(5, 85)))
reports.sort(key=lambda r: r["created_at"])
for i, r in enumerate(reports):
    r["report_id"] = f"MR{i+1:04d}"

# ---------------------------------------------------------------- write
def to_json(o):
    if isinstance(o, dict): return {k: to_json(v) for k, v in o.items()}
    if isinstance(o, list): return [to_json(v) for v in o]
    if isinstance(o, dt.datetime): return iso(o)
    return o

import os
os.makedirs(OUT, exist_ok=True)
for name, data in [("users", users), ("stations", stations), ("bikes", bikes),
                   ("rentals", rentals), ("maintenance_reports", reports)]:
    with open(f"{OUT}/{name}.json", "w") as f:
        json.dump(to_json(data), f, indent=2)
    print(f"{name:20s} {len(data)}")
