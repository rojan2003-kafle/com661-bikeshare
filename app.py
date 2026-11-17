from flask import Flask, request
from utils import ApiError, respond
from blueprints.auth.auth import auth_bp
from blueprints.stations.stations import stations_bp
from blueprints.bikes.bikes import bikes_bp
from blueprints.rentals.rentals import rentals_bp
from blueprints.payments.payments import payments_bp
from blueprints.maintenance.maintenance import maintenance_bp
from blueprints.admin.admin import admin_bp

app = Flask(__name__)
from flask_cors import CORS
CORS(app, resources={r"/api/*": {"origins": "http://localhost:4200"}})
app.json.sort_keys = False      # keep JSON fields in the order we wrote them

for bp in [auth_bp, stations_bp, bikes_bp, rentals_bp, payments_bp, maintenance_bp, admin_bp]:
    app.register_blueprint(bp, url_prefix="/api/v1.0")


# ---------- error handlers: every error comes back as JSON ----------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return respond({"error": e.message, "status": e.status}, e.status)


@app.errorhandler(404)
def not_found(e):
    return respond({"error": f"Endpoint {request.path} does not exist", "status": 404}, 404)


@app.errorhandler(405)
def method_not_allowed(e):
    return respond({"error": f"Method {request.method} not allowed on {request.path}", "status": 405}, 405)


if __name__ == "__main__":
    app.run(debug=True, port=5001)
