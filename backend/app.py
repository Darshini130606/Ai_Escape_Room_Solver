"""Flask application: serves the page and the JSON API.

Run from the project folder:   python -m backend.app
"""
from __future__ import annotations

import os

from flask import Flask, jsonify, request, send_from_directory

from .game_state import Game, GameError

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")


def create_app(game: Game = None) -> Flask:
    app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="/static")
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False
    game = game or Game()
    app.config["GAME"] = game

    # ---------------- helpers ----------------
    def body() -> dict:
        """The JSON body as a dict. A missing or non-object body counts as empty."""
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}

    def need_json_object():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise GameError("Send a JSON object as the request body.", 400)
        return data

    def ok(payload: dict, status: int = 200):
        payload = dict(payload)
        payload.setdefault("ok", True)
        return jsonify(payload), status

    @app.errorhandler(GameError)
    def on_game_error(exc: GameError):
        payload = {"ok": False, "error": exc.message}
        payload.update(exc.extra)
        payload["state"] = game.to_dict()
        return jsonify(payload), exc.status

    @app.errorhandler(404)
    def on_404(_exc):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "Unknown API route."}), 404
        return "Not found", 404

    @app.errorhandler(405)
    def on_405(_exc):
        return jsonify({"ok": False, "error": "Method not allowed for this route."}), 405

    @app.errorhandler(Exception)
    def on_unexpected(exc):
        if hasattr(exc, "code") and isinstance(exc.code, int):   # werkzeug HTTP errors
            return jsonify({"ok": False, "error": getattr(exc, "description", "Request failed.")}), exc.code
        app.logger.exception("Unexpected error")
        return jsonify({"ok": False, "error": "Something went wrong on the server."}), 500

    # ---------------- pages and files ----------------
    @app.get("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.get("/assets/<path:filename>")
    def assets(filename):
        return send_from_directory(ASSETS_DIR, filename)

    @app.after_request
    def no_cache(resp):
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    # ---------------- state ----------------
    @app.get("/api/state")
    def api_state():
        return ok({"state": game.to_dict()})

    @app.post("/api/reset")
    def api_reset():
        game.reset()
        return ok({"state": game.to_dict(), "message": "Game restarted."})

    @app.post("/api/navigate")
    def api_navigate():
        data = need_json_object()
        return ok({"state": game.navigate(data.get("room"))})

    @app.post("/api/hint")
    def api_hint():
        hint = game.give_hint()
        return ok({"hint": hint, "state": game.to_dict()})

    @app.post("/api/inspect")
    def api_inspect():
        data = need_json_object()
        result = game.inspect(data.get("item"))
        return ok({"result": result, "state": game.to_dict()})

    # ---------------- room 1 ----------------
    @app.get("/api/maze")
    def api_maze():
        return ok({"maze": game.to_dict()["maze"]})

    @app.post("/api/maze/algorithm")
    def api_maze_algorithm():
        data = need_json_object()
        return ok({"state": game.set_algorithm(data.get("algorithm"))})

    @app.post("/api/maze/solve")
    def api_maze_solve():
        data = body()
        result = game.maze_solve(data.get("algorithm"))
        return ok({"result": result, "state": game.to_dict()})

    @app.post("/api/maze/apply")
    def api_maze_apply():
        data = body()
        state = game.maze_apply(data.get("algorithm"))
        return ok({"state": state})

    @app.post("/api/maze/move")
    def api_maze_move():
        data = need_json_object()
        return ok({"state": game.maze_move(data.get("direction"))})

    @app.post("/api/maze/complete")
    def api_maze_complete():
        result = game.maze_complete()
        return ok({"result": result, "state": game.to_dict()})

    # ---------------- room 2 ----------------
    @app.get("/api/safe")
    def api_safe():
        result = game.safe_clues()
        return ok({"result": result, "state": game.to_dict()})

    @app.get("/api/safe/solve")
    def api_safe_solve():
        result = game.safe_solve()
        return ok({"result": result, "state": game.to_dict()})

    @app.post("/api/safe/check")
    def api_safe_check():
        data = need_json_object()
        if "code" not in data:
            raise GameError("Send the code as {\"code\": \"042\"}.", 400)
        result = game.safe_check(data.get("code"))
        return ok({"result": result, "state": game.to_dict()})

    @app.post("/api/safe/apply")
    def api_safe_apply():
        result = game.safe_apply()
        return ok({"result": result, "state": game.to_dict()})

    # ---------------- room 3 ----------------
    @app.get("/api/switches")
    def api_switches():
        return ok({"result": game.switches_state(), "state": game.to_dict()})

    @app.post("/api/switches/toggle")
    def api_switches_toggle():
        data = need_json_object()
        result = game.switch_toggle(data.get("switch"))
        return ok({"result": result, "state": game.to_dict()})

    @app.post("/api/switches/check")
    def api_switches_check():
        data = body()
        result = game.switch_check(data.get("switches") if "switches" in data else None)
        return ok({"result": result, "state": game.to_dict()})

    @app.get("/api/switches/solve")
    def api_switches_solve():
        result = game.switch_solve()
        return ok({"result": result, "state": game.to_dict()})

    @app.post("/api/switches/apply")
    def api_switches_apply():
        result = game.switch_apply()
        return ok({"result": result, "state": game.to_dict()})

    # ---------------- exit ----------------
    @app.get("/api/exit")
    def api_exit():
        return ok({"result": game.exit_status(), "state": game.to_dict()})

    @app.post("/api/exit/open")
    def api_exit_open():
        result = game.exit_open()
        return ok({"result": result, "state": game.to_dict()})

    return app


app = create_app()

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    print("AI Escape Room Solver running at http://%s:%d" % (host, port))
    app.run(host=host, port=port, debug=False)
