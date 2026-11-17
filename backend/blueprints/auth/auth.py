from datetime import timedelta

import bcrypt
import jwt
from flask import Blueprint, request, g

import globals
from decorators import jwt_required
from utils import (ApiError, respond, get_data, require_fields, parse_str,
                   parse_email, parse_password, next_id, now)

auth_bp = Blueprint("auth_bp", __name__)


@auth_bp.route("/auth/register", methods=["POST"])
def register():
    data = get_data()
    require_fields(data, ["name", "email", "password"])
    name = parse_str(data["name"], "name", 2, 60)
    email = parse_email(data["email"])
    password = parse_password(data["password"])

    if globals.users.find_one({"email": email}):
        raise ApiError(409, "An account with this email already exists")

    new_user = {
        "user_id": next_id("users", globals.users, "user_id", "U", 3),
        "name": name,
        "email": email,
        "password_hash": bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
        "role": "rider",            # everyone signs up as a rider; admins promote staff
        "created_at": now(),
    }
    globals.users.insert_one(new_user)
    new_user.pop("_id", None)
    return respond({"message": "Account created", "user": new_user}, 201)


@auth_bp.route("/auth/login", methods=["POST"])
def login():
    auth = request.authorization       # Basic Auth: username = email
    if not auth or not auth.username or not auth.password:
        raise ApiError(401, "Login required - send email and password using Basic Auth")

    user = globals.users.find_one({"email": auth.username.strip().lower()})
    if user is None or not bcrypt.checkpw(auth.password.encode(), user["password_hash"].encode()):
        raise ApiError(401, "Incorrect email or password")

    token = jwt.encode({"user_id": user["user_id"], "role": user["role"],
                        "exp": now() + timedelta(minutes=60)},
                       globals.secret_key, algorithm="HS256")
    return respond({"token": token, "user_id": user["user_id"], "name": user["name"],
                    "role": user["role"]}, 200)


@auth_bp.route("/auth/logout", methods=["POST"])
@jwt_required
def logout():
    globals.blacklist.insert_one({"token": g.token, "user_id": g.user_id, "logged_out_at": now()})
    return respond({"message": "Logged out"}, 200)


@auth_bp.route("/auth/me", methods=["GET"])
@jwt_required
def my_profile():
    user = globals.users.find_one({"user_id": g.user_id}, {"_id": 0, "password_hash": 0})
    if user is None:
        raise ApiError(404, "User no longer exists")
    return respond(user, 200)
