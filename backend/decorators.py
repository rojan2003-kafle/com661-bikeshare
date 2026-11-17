from functools import wraps

import jwt
from flask import request, g

import globals
from utils import ApiError


def jwt_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        token = request.headers.get("x-access-token")
        if not token:
            raise ApiError(401, "Token is missing - log in and send it in the x-access-token header")
        try:
            data = jwt.decode(token, globals.secret_key, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise ApiError(401, "Token has expired - please log in again")
        except jwt.InvalidTokenError:
            raise ApiError(401, "Token is invalid")
        if globals.blacklist.find_one({"token": token}):
            raise ApiError(401, "Token has been cancelled (logged out)")
        # remember who is logged in for the rest of this request
        g.user_id = data["user_id"]
        g.role = data["role"]
        g.token = token
        return func(*args, **kwargs)
    return wrapper


def role_required(*roles):
    """@role_required("admin")  or  @role_required("mechanic", "admin")"""
    def decorator(func):
        @wraps(func)
        @jwt_required
        def wrapper(*args, **kwargs):
            if g.role not in roles:
                raise ApiError(403, f"Access denied - this action needs role: {' or '.join(roles)}")
            return func(*args, **kwargs)
        return wrapper
    return decorator
