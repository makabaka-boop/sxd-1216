from flask import Flask, jsonify
from flask_cors import CORS

from constants import HOST, PORT
from storage import storage
from routes.auth_routes import bp as auth_bp
from routes.admin_routes import bp as admin_bp
from routes.inspector_routes import bp as inspector_bp
from routes.appeal_routes import bp as appeal_bp
from routes.review_routes import bp as review_bp
from routes.inspection_routes import bp as inspection_bp
from routes.stats_routes import bp as stats_bp
from routes.risk_routes import bp as risk_bp
from routes.rectification_routes import bp as rectification_bp


def create_app():
    app = Flask(__name__)
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    storage.seed_defaults()

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(inspector_bp)
    app.register_blueprint(appeal_bp)
    app.register_blueprint(review_bp)
    app.register_blueprint(inspection_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(risk_bp)
    app.register_blueprint(rectification_bp)

    @app.get("/")
    def index():
        return jsonify({
            "name": "客服中心质检抽检系统",
            "version": "1.1.0",
            "endpoints": [
                "/api/auth/login", "/api/auth/me",
                "/api/admin/*", "/api/inspector/*", "/api/appeals",
                "/api/reviews", "/api/inspections", "/api/stats/*", "/api/risk/alerts",
                "/api/rectifications/*",
            ],
            "default_users": {
                "admin": "admin123",
                "inspector": "inspector123",
                "leader": "leader123",
            },
        })

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "port": PORT})

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"code": 404, "message": "资源不存在"}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({"code": 405, "message": "方法不允许"}), 405

    @app.errorhandler(500)
    def server_error(e):
        return jsonify({"code": 500, "message": "服务器内部错误"}), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=True)
