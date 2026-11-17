import secrets
from flask import Blueprint, g
import globals
from decorators import jwt_required, role_required
from utils import ApiError, respond, get_data, require_fields, parse_enum, now
from blueprints.rentals.rentals import find_rental

payments_bp = Blueprint("payments_bp", __name__)

# Stripe test payment methods (same names Stripe uses in test mode)
SUCCEED = {"pm_card_visa": "visa", "pm_card_mastercard": "mastercard", "pm_card_amex": "amex"}
DECLINE = {"pm_card_chargedeclined": "card_declined",
           "pm_card_visa_chargedeclinedinsufficientfunds": "insufficient_funds"}


@payments_bp.route("/payments/create", methods=["POST"])
@jwt_required
def create_payment():
    data = get_data()
    require_fields(data, ["rental_id"])
    rental = find_rental(str(data["rental_id"]).strip())
    if rental["user_id"] != g.user_id:
        raise ApiError(403, "You can only pay for your own rentals")
    if rental["status"] != "completed":
        raise ApiError(409, f"Only completed rides can be paid for - this one is {rental['status']}")
    if rental["payment"] and rental["payment"].get("status") == "succeeded":
        raise ApiError(409, "This ride has already been paid")

    method = parse_enum(data.get("payment_method", "pm_card_visa"), "payment_method",
                        list(SUCCEED) + list(DECLINE))
    if method in DECLINE:
        # store the failed attempt using dot notation to update ONE field inside the sub-document
        globals.rentals.update_one({"rental_id": rental["rental_id"]},
                                   {"$set": {"payment.status": "failed", "payment.last_attempt": now()}})
        raise ApiError(402, f"Payment declined: {DECLINE[method]}")

    payment = {"payment_id": "pi_test_" + secrets.token_hex(8), "amount": rental["total_cost"],
               "currency": "GBP", "method": "card", "card_brand": SUCCEED[method],
               "status": "succeeded", "paid_at": now()}
    globals.rentals.update_one({"rental_id": rental["rental_id"]}, {"$set": {"payment": payment}})
    return respond({"message": f"Payment of £{payment['amount']:.2f} successful",
                    "rental_id": rental["rental_id"], "payment": payment}, 201)


@payments_bp.route("/payments/<string:rental_id>", methods=["GET"])
@jwt_required
def payment_status(rental_id):
    rental = find_rental(rental_id)
    payment = rental["payment"] or {"status": "not_applicable"}
    return respond({"rental_id": rental_id, "total_cost": rental["total_cost"],
                    "paid": payment.get("status") == "succeeded", "payment": payment}, 200)


@payments_bp.route("/payments/<string:rental_id>/refund", methods=["POST"])
@role_required("admin")
def refund_payment(rental_id):
    rental = find_rental(rental_id)
    if not rental["payment"] or rental["payment"].get("status") != "succeeded":
        raise ApiError(409, "Only a successful payment can be refunded")
    globals.rentals.update_one({"rental_id": rental_id},
                               {"$set": {"payment.status": "refunded", "payment.refunded_at": now()}})
    return respond({"message": "Payment refunded", "payment": find_rental(rental_id)["payment"]}, 200)
