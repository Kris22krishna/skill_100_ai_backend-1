from flask import Flask
from blueprints.payment_blueprint import payment_bp
from dotenv import load_dotenv


load_dotenv()
app = Flask(__name__)


app.register_blueprint(blueprint=payment_bp, url_prefix="/payment")


if __name__ == "__main__":
    app.run(debug=True)