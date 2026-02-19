from flask import Blueprint, request, jsonify
from services.get_kolkata_timestamp import get_kolkata_timestamp
import razorpay
import os

payment_bp = Blueprint("payment", __name__)
client = razorpay.Client(auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET")))
client.set_app_details({"title":"Skill 100 AI", "version":"1.0.0"})

@payment_bp.route("/create-order", methods=["POST"])
def create_order():
    data = request.get_json(silent=True)
    
    if data is None:
        return jsonify({"error": "Please provide a valid arguments"}), 400

    if "amount" not in data:
        return jsonify({"error": "Amount is required"}), 400
    
    if isinstance(data['amount'], float):
        return jsonify({"error": "Amount is of type float"}), 400

    if "receipt" not in data:
        return jsonify({"error": "Please provide a valid recipt id"}), 400

    DATA = {
        "amount": data['amount'],
        "currency": "INR",
        "receipt": data['receipt'],
        "notes": {
            "purchase_initiated_at": get_kolkata_timestamp(),
        }
    }
    order = client.order.create(data=DATA)
    return jsonify(order)


@payment_bp.route('/handle-order-callback', methods=["GET", "POST"])
def handle_order_callback():
    print(request.query_string)
    return "SUCCESS"
