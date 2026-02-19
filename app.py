from flask import Flask
from blueprints.payment_blueprint import payment_bp
from dotenv import load_dotenv
from flask_cors import CORS


load_dotenv()
app = Flask(__name__)
CORS(app)


app.register_blueprint(blueprint=payment_bp, url_prefix="/payment")


if __name__ == "__main__":
    app.run(debug=True)