from pymongo import MongoClient

# connect to the MongoDB server running on your Mac
client = MongoClient("mongodb://127.0.0.1:27017", tz_aware=True)
db = client.bikeshare          # the database we imported

secret_key = "com661-bikeshare-secret"   # used to sign login tokens

# one variable per collection, so other files can just use globals.stations etc.
users = db.users
stations = db.stations
bikes = db.bikes
rentals = db.rentals
maintenance = db.maintenance_reports
blacklist = db.blacklist        # tokens of users who logged out
counters = db.counters          # for readable IDs like U151
