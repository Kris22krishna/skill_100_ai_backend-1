import os

from flask import Flask
from dotenv import load_dotenv
from flask_cors import CORS

load_dotenv()

from blueprints.payment_blueprint import payment_bp  # noqa: E402 (needs env loaded)

app = Flask(__name__)

# Only our own frontends may call the payment API from a browser.
_origins = [o.strip() for o in os.getenv(
    "ALLOWED_ORIGINS",
    "https://www.skill100.ai,https://skill100.ai,http://localhost:5173,http://127.0.0.1:5173",
).split(",") if o.strip()]
# supports_credentials: the frontend's fetch wrapper sends credentials mode
# 'include', so preflights require Access-Control-Allow-Credentials: true.
CORS(app, origins=_origins, supports_credentials=True)

app.register_blueprint(blueprint=payment_bp, url_prefix="/payment")


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(debug=True, port=5001)