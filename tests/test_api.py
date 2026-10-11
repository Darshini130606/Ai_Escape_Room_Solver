"""Tests for the Flask app and the game state machine (uses Flask's test client)."""
import unittest

from backend.app import create_app
from backend.game_state import Game


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.game = Game()
        self.app = create_app(self.game)
        self.client = self.app.test_client()

    # helpers
    def get(self, path):
        return self.client.get(path)

    def post(self, path, payload=None):
        return self.client.post(path, json=payload if payload is not None else {})

    def state(self):
        return self.get("/api/state").get_json()["state"]

    def finish_maze(self):
        return self.post("/api/maze/apply", {"algorithm": "astar"})

    def finish_safe(self):
        return self.post("/api/safe/check", {"code": "042"})

    def finish_switches(self):
        return self.post("/api/switches/check", {"switches": {"A": True, "B": True, "C": False}})


class AppBasicsTests(ApiTestCase):
    def test_app_initialises(self):
        self.assertIsNotNone(self.app)
        self.assertIs(self.app.config["GAME"], self.game)

    def test_homepage(self):
        r = self.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"AI Escape Room Solver", r.data)
        self.assertIn(b"/static/script.js", r.data)
        r.close()

    def test_css_js_and_assets_are_served(self):
        for path, kind in [("/static/style.css", "css"), ("/static/script.js", "javascript"),
                           ("/assets/keycard.svg", "svg"), ("/assets/chip.svg", "svg"),
                           ("/assets/logo.svg", "svg"), ("/assets/door.svg", "svg")]:
            with self.subTest(path=path):
                r = self.get(path)
                self.assertEqual(r.status_code, 200)
                self.assertIn(kind, r.content_type)
                r.close()

    def test_unknown_routes(self):
        self.assertEqual(self.get("/api/nope").status_code, 404)
        self.assertEqual(self.get("/api/nope").get_json()["ok"], False)
        self.assertEqual(self.client.delete("/api/state").status_code, 405)


class InitialStateTests(ApiTestCase):
    def test_initial_state(self):
        s = self.state()
        self.assertEqual(s["current_room"], 1)
        self.assertEqual([r["status"] for r in s["rooms"]], ["active", "locked", "locked", "locked"])
        self.assertEqual(s["stats"]["moves"], 0)
        self.assertEqual(s["stats"]["hints"], 0)
        self.assertEqual(s["mission"]["progress"], 0)
        self.assertFalse(s["mission"]["complete"])
        self.assertTrue(all(not i["collected"] for i in s["inventory"]))
        self.assertTrue(all(not o["done"] for o in s["objectives"]))
        self.assertEqual(s["maze"]["pos"], s["maze"]["start"])
        self.assertEqual(s["safe"]["clues"], [])          # the clue paper is not handed out early
        self.assertFalse(s["switches"]["available"])
        self.assertEqual(s["log"][0]["text"], "Game initialized.")

    def test_state_does_not_reveal_the_safe_code(self):
        self.assertNotIn("042", str(self.state()))
        self.finish_maze()
        self.assertNotIn("042", str(self.state()["safe"]))

    def test_maze_endpoint(self):
        m = self.get("/api/maze").get_json()["maze"]
        self.assertEqual(len(m["layout"]), 9)


class MazeApiTests(ApiTestCase):
    def test_solve_each_algorithm(self):
        for alg in ["bfs", "dfs", "ucs", "astar"]:
            with self.subTest(alg=alg):
                r = self.post("/api/maze/solve", {"algorithm": alg})
                self.assertEqual(r.status_code, 200)
                res = r.get_json()["result"]
                self.assertTrue(res["found"])
                self.assertEqual(res["algorithm"], alg)
        self.assertEqual(self.state()["stats"]["moves"], 0)       # solving does not move the player

    def test_solve_rejects_unknown_algorithm(self):
        r = self.post("/api/maze/solve", {"algorithm": "magic"})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.get_json()["ok"])

    def test_solve_defaults_to_selected_algorithm(self):
        self.post("/api/maze/algorithm", {"algorithm": "ucs"})
        self.assertEqual(self.post("/api/maze/solve").get_json()["result"]["algorithm"], "ucs")

    def test_algorithm_selection_validated(self):
        self.assertEqual(self.post("/api/maze/algorithm", {"algorithm": "x"}).status_code, 400)
        self.assertEqual(self.post("/api/maze/algorithm", {}).status_code, 400)

    def test_walls_block_movement(self):
        r = self.post("/api/maze/move", {"direction": "up"})     # start (1,7): wall above
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.state()["maze"]["pos"], [1, 7])
        self.assertEqual(self.state()["stats"]["moves"], 0)

    def test_bad_move_requests(self):
        self.assertEqual(self.post("/api/maze/move", {"direction": "north"}).status_code, 400)
        self.assertEqual(self.post("/api/maze/move", {}).status_code, 400)
        self.assertEqual(self.post("/api/maze/move", {"direction": 5}).status_code, 400)
        self.assertEqual(self.client.post("/api/maze/move", data="not json",
                                          content_type="application/json").status_code, 400)

    def test_manual_walk_collects_keycard_then_exit_unlocks(self):
        route = ["left"] * 4 + ["down"] * 2 + ["left"] * 2 + ["down"] * 2 + ["right"] * 2
        for step in route:
            self.assertEqual(self.post("/api/maze/move", {"direction": step}).status_code, 200)
        s = self.state()
        self.assertEqual(s["maze"]["pos"], [5, 3])
        self.assertTrue(s["inventory"][0]["collected"])
        self.assertEqual(s["stats"]["moves"], 12)
        self.assertFalse(s["maze"]["complete"])
        for step in ["left"] * 2 + ["up"] * 2 + ["right"] * 2 + ["up"] * 2 + ["left"] * 2:
            self.post("/api/maze/move", {"direction": step})
        s = self.state()
        self.assertTrue(s["maze"]["complete"])
        self.assertEqual(s["current_room"], 2)
        self.assertEqual(s["maze"]["hazards_crossed"], 0)
        self.assertTrue([o for o in s["objectives"] if o["id"] == "avoid_lasers"][0]["done"])

    def test_exit_needs_the_keycard(self):
        # walk along the top corridor straight at the locked door
        for _ in range(5):
            self.post("/api/maze/move", {"direction": "left"})
        r = self.post("/api/maze/move", {"direction": "left"})   # (1,2) -> (1,1) is the door
        self.assertEqual(self.state()["maze"]["pos"], [1, 2])
        self.assertEqual(r.status_code, 409)
        self.assertIn("locked", r.get_json()["error"])
        self.assertFalse(self.state()["maze"]["complete"])

    def test_complete_endpoint_cannot_be_used_to_cheat(self):
        r = self.post("/api/maze/complete")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.state()["rooms"][1]["status"], "locked")

    def test_complete_endpoint_after_finishing_is_idempotent(self):
        self.finish_maze()
        r = self.post("/api/maze/complete")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["result"]["already"])

    def test_hazard_steps_are_counted(self):
        self.post("/api/maze/move", {"direction": "down"})       # (2,7) is a laser grid
        s = self.state()
        self.assertEqual(s["maze"]["hazards_crossed"], 1)
        self.assertEqual(s["maze"]["cost"], 5)
        self.assertEqual(s["output"]["level"], "error")

    def test_apply_ai_solution_each_algorithm(self):
        for alg in ["bfs", "dfs", "ucs", "astar"]:
            with self.subTest(alg=alg):
                self.post("/api/reset")
                r = self.post("/api/maze/apply", {"algorithm": alg})
                self.assertEqual(r.status_code, 200)
                s = self.state()
                self.assertTrue(s["maze"]["complete"])
                self.assertTrue(s["inventory"][0]["collected"])

    def test_apply_twice_is_rejected(self):
        self.finish_maze()
        self.assertEqual(self.post("/api/maze/apply").status_code, 409)
        self.assertEqual(self.post("/api/maze/move", {"direction": "up"}).status_code, 409)

    def test_apply_astar_costs_match_solver(self):
        self.finish_maze()
        s = self.state()
        self.assertEqual(s["stats"]["moves"], 22)
        self.assertEqual(s["maze"]["cost"], 22)


class SafeApiTests(ApiTestCase):
    def test_locked_until_maze_done(self):
        self.assertEqual(self.get("/api/safe").status_code, 403)
        self.assertEqual(self.get("/api/safe/solve").status_code, 403)
        self.assertEqual(self.post("/api/safe/check", {"code": "042"}).status_code, 403)
        self.assertEqual(self.post("/api/safe/apply").status_code, 403)
        self.assertEqual(self.post("/api/navigate", {"room": 2}).status_code, 403)
        self.assertEqual(self.state()["inventory"][1]["collected"], False)

    def test_clues_visible_after_maze(self):
        self.finish_maze()
        s = self.state()
        self.assertEqual(len(s["safe"]["clues"]), 7)
        self.assertFalse(s["safe"]["clues_read"])
        r = self.get("/api/safe")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.state()["safe"]["clues_read"])

    def test_wrong_codes_are_rejected_with_feedback(self):
        self.finish_maze()
        r = self.post("/api/safe/check", {"code": "123"})
        self.assertEqual(r.status_code, 200)
        res = r.get_json()["result"]
        self.assertFalse(res["correct"])
        self.assertEqual(res["broken"], [1, 3, 4, 5, 6])
        s = self.state()
        self.assertFalse(s["safe"]["unlocked"])
        self.assertFalse(s["inventory"][1]["collected"])
        self.assertEqual(len(s["safe"]["tries"]), 1)
        self.assertEqual(s["stats"]["moves"], 23)

    def test_correct_code_opens_safe_and_gives_chip(self):
        self.finish_maze()
        r = self.finish_safe()
        self.assertTrue(r.get_json()["result"]["correct"])
        s = self.state()
        self.assertTrue(s["safe"]["unlocked"])
        self.assertTrue(s["inventory"][1]["collected"])
        self.assertEqual(s["current_room"], 3)
        self.assertEqual(s["rooms"][1]["status"], "complete")

    def test_malformed_code_requests(self):
        self.finish_maze()
        for payload in [{}, {"code": ""}, {"code": "12"}, {"code": "12a"}, {"code": 42}, {"code": None}, {"code": "0420"}]:
            with self.subTest(payload=payload):
                self.assertEqual(self.post("/api/safe/check", payload).status_code, 400)
        self.assertEqual(self.state()["stats"]["moves"], 22)       # none of them counted
        self.assertEqual(self.client.post("/api/safe/check", data="[1]", content_type="application/json").status_code, 400)

    def test_repeated_correct_submission_is_harmless(self):
        self.finish_maze()
        self.finish_safe()
        moves = self.state()["stats"]["moves"]
        r = self.finish_safe()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["result"]["already"])
        self.assertEqual(self.state()["stats"]["moves"], moves)

    def test_solver_endpoint(self):
        self.finish_maze()
        res = self.get("/api/safe/solve").get_json()["result"]
        self.assertEqual(res["solutions"], ["042"])
        self.assertFalse(self.state()["safe"]["unlocked"])         # solving alone does not open the safe

    def test_apply_ai_solution(self):
        self.finish_maze()
        self.assertEqual(self.post("/api/safe/apply").status_code, 200)
        self.assertTrue(self.state()["safe"]["unlocked"])


class SwitchApiTests(ApiTestCase):
    def reach_room3(self):
        self.finish_maze()
        self.finish_safe()

    def test_locked_until_safe_open(self):
        self.finish_maze()
        for method, path in [("get", "/api/switches"), ("post", "/api/switches/toggle"),
                             ("post", "/api/switches/check"), ("get", "/api/switches/solve"),
                             ("post", "/api/switches/apply")]:
            r = getattr(self, method)(path) if method == "get" else self.post(path, {"switch": "A"})
            self.assertEqual(r.status_code, 403, path)
        self.assertEqual(self.post("/api/navigate", {"room": 3}).status_code, 403)

    def test_initial_switches_and_toggle(self):
        self.reach_room3()
        res = self.get("/api/switches").get_json()["result"]
        self.assertEqual(res["config"], {"A": True, "B": True, "C": True})
        self.assertEqual(res["evaluation"]["conflicts"], ["short_circuit"])
        res = self.post("/api/switches/toggle", {"switch": "C"}).get_json()["result"]
        self.assertFalse(res["config"]["C"])
        self.assertEqual(res["evaluation"]["conflicts"], [])
        self.assertFalse(res["power_restored"])                   # toggling alone restores nothing
        self.assertFalse(self.state()["rooms"][2]["status"] == "complete")

    def test_invalid_toggle(self):
        self.reach_room3()
        for payload in [{}, {"switch": "Z"}, {"switch": 1}, {"switch": None}]:
            self.assertEqual(self.post("/api/switches/toggle", payload).status_code, 400)

    def test_invalid_configuration_is_rejected(self):
        self.reach_room3()
        r = self.post("/api/switches/check", {})             # all three still on: short circuit
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.get_json()["result"]["evaluation"]["success"])
        self.assertFalse(self.state()["switches"]["power_restored"])
        self.assertEqual(self.state()["output"]["level"], "error")
        for cfg in [{"A": True, "B": False, "C": False}, {"A": False, "B": True, "C": False},
                    {"A": False, "B": False, "C": False}]:
            r = self.post("/api/switches/check", {"switches": cfg})
            self.assertFalse(r.get_json()["result"]["evaluation"]["success"], cfg)
        self.assertEqual(self.post("/api/switches/check", {"switches": {"A": True}}).status_code, 400)
        self.assertEqual(self.post("/api/switches/check", {"switches": "on"}).status_code, 400)

    def test_valid_configuration_restores_power(self):
        self.reach_room3()
        r = self.finish_switches()
        self.assertTrue(r.get_json()["result"]["evaluation"]["success"])
        s = self.state()
        self.assertTrue(s["switches"]["power_restored"])
        self.assertEqual(s["current_room"], 4)
        self.assertEqual(s["rooms"][2]["status"], "complete")
        self.assertEqual(self.post("/api/switches/toggle", {"switch": "A"}).status_code, 409)

    def test_toggling_to_the_solution_then_checking(self):
        self.reach_room3()
        self.post("/api/switches/toggle", {"switch": "C"})
        self.assertTrue(self.post("/api/switches/check").get_json()["result"]["evaluation"]["success"])

    def test_solver_and_apply(self):
        self.reach_room3()
        res = self.get("/api/switches/solve").get_json()["result"]
        self.assertEqual(res["solution"], {"A": True, "B": True, "C": False})
        self.assertFalse(self.state()["switches"]["power_restored"])
        self.assertEqual(self.post("/api/switches/apply").status_code, 200)
        self.assertTrue(self.state()["switches"]["power_restored"])


class ExitAndFlowTests(ApiTestCase):
    def play_to_exit(self):
        self.finish_maze()
        self.finish_safe()
        self.finish_switches()

    def test_exit_requirements_listed_when_locked(self):
        r = self.get("/api/exit").get_json()["result"]
        self.assertFalse(r["all_met"])
        self.assertEqual(len(r["requirements"]), 5)
        self.assertTrue(all(not q["met"] for q in r["requirements"]))
        r = self.post("/api/exit/open")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(len(r.get_json()["requirements"]), 5)
        self.assertFalse(self.state()["mission"]["complete"])

    def test_partial_progress_keeps_exit_locked(self):
        self.finish_maze()
        self.finish_safe()
        met = {q["id"]: q["met"] for q in self.get("/api/exit").get_json()["result"]["requirements"]}
        self.assertEqual(met, {"maze": True, "keycard": True, "safe": True, "chip": True, "power": False})
        self.assertEqual(self.post("/api/exit/open").status_code, 403)
        self.assertEqual(self.post("/api/navigate", {"room": 4}).status_code, 403)

    def test_successful_escape(self):
        self.play_to_exit()
        r = self.post("/api/exit/open")
        self.assertEqual(r.status_code, 200)
        s = self.state()
        self.assertTrue(s["mission"]["complete"])
        self.assertEqual(s["mission"]["status"], "Escaped")
        self.assertEqual(s["mission"]["progress"], 100)
        self.assertTrue(all(o["done"] for o in s["objectives"] if not o["optional"]))
        self.assertFalse(s["stats"]["running"])
        self.assertTrue(any(e["text"] == "Mission completed. You escaped!" for e in s["log"]))
        self.assertTrue(self.post("/api/exit/open").get_json()["result"]["already"])

    def test_progress_is_calculated_from_objectives(self):
        before = self.state()["mission"]["progress"]
        self.finish_maze()
        mid = self.state()["mission"]["progress"]
        self.assertGreater(mid, before)
        self.finish_safe()
        self.assertGreater(self.state()["mission"]["progress"], mid)

    def test_navigation_between_unlocked_rooms(self):
        self.finish_maze()
        self.assertEqual(self.post("/api/navigate", {"room": 1}).get_json()["state"]["current_room"], 1)
        self.assertEqual(self.post("/api/navigate", {"room": 2}).get_json()["state"]["current_room"], 2)
        for bad in [{}, {"room": 9}, {"room": "2"}, {"room": True}, {"room": 0}]:
            self.assertEqual(self.post("/api/navigate", bad).status_code, 400)

    def test_hints_are_counted_and_do_not_solve(self):
        r = self.post("/api/hint")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.state()["stats"]["hints"], 1)
        self.assertFalse(self.state()["maze"]["complete"])
        self.finish_maze()
        h1 = self.post("/api/hint").get_json()["hint"]["text"]
        h2 = self.post("/api/hint").get_json()["hint"]["text"]
        self.assertNotEqual(h1, h2)
        self.assertEqual(self.state()["stats"]["hints"], 3)
        self.assertFalse(self.state()["safe"]["unlocked"])

    def test_inspect_items(self):
        self.assertEqual(self.post("/api/inspect", {"item": "keycard"}).status_code, 403)
        self.assertEqual(self.post("/api/inspect", {"item": "banana"}).status_code, 400)
        self.finish_maze()
        r = self.post("/api/inspect", {"item": "keycard"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("Switch C", r.get_json()["result"]["text"])
        self.assertEqual(self.post("/api/inspect", {"item": "chip"}).status_code, 403)

    def test_log_records_real_events_only(self):
        texts = [e["text"] for e in self.state()["log"]]
        self.assertFalse(any("collected" in t.lower() for t in texts))
        self.finish_maze()
        texts = [e["text"] for e in self.state()["log"]]
        self.assertTrue(any("Keycard collected" in t for t in texts))
        self.assertFalse(any("Safe unlocked" in t for t in texts))
        self.post("/api/safe/check", {"code": "000"})
        self.assertFalse(any("Safe unlocked" in e["text"] for e in self.state()["log"]))
        self.finish_safe()
        self.assertTrue(any("Safe unlocked" in e["text"] for e in self.state()["log"]))


class ResetTests(ApiTestCase):
    def test_reset_restores_everything(self):
        self.finish_maze()
        self.finish_safe()
        self.finish_switches()
        self.post("/api/exit/open")
        self.post("/api/hint")
        self.assertTrue(self.state()["mission"]["complete"])
        fresh = Game().to_dict()
        r = self.post("/api/reset")
        self.assertEqual(r.status_code, 200)
        s = self.state()
        self.assertEqual(s["current_room"], 1)
        self.assertEqual(s["stats"]["moves"], 0)
        self.assertEqual(s["stats"]["hints"], 0)
        self.assertTrue(s["stats"]["running"])
        self.assertFalse(s["mission"]["complete"])
        self.assertEqual(s["mission"]["progress"], 0)
        self.assertEqual([r2["status"] for r2 in s["rooms"]], ["active", "locked", "locked", "locked"])
        self.assertTrue(all(not i["collected"] for i in s["inventory"]))
        self.assertTrue(all(not o["done"] for o in s["objectives"]))
        self.assertEqual(s["maze"]["pos"], s["maze"]["start"])
        self.assertEqual(s["maze"]["trail"], [s["maze"]["start"]])
        self.assertEqual(s["safe"]["tries"], [])
        self.assertFalse(s["safe"]["unlocked"])
        self.assertEqual(s["ai"], {})
        self.assertIsNone(s["hint"])
        self.assertEqual([e["text"] for e in s["log"]], [e["text"] for e in fresh["log"]])
        self.assertFalse(s["switches"]["available"])

    def test_game_is_replayable_after_reset(self):
        for _ in range(2):
            self.finish_maze()
            self.finish_safe()
            self.finish_switches()
            self.assertEqual(self.post("/api/exit/open").status_code, 200)
            self.post("/api/reset")


class RobustnessTests(ApiTestCase):
    def test_get_on_post_routes(self):
        self.assertEqual(self.get("/api/reset").status_code, 405)
        self.assertEqual(self.get("/api/maze/move").status_code, 405)

    def test_errors_return_json_and_state(self):
        r = self.post("/api/maze/move", {"direction": "up"})
        data = r.get_json()
        self.assertFalse(data["ok"])
        self.assertIn("error", data)
        self.assertIn("state", data)

    def test_unexpected_exception_is_a_json_500(self):
        def boom():
            raise RuntimeError("kaboom")
        self.game.exit_status = boom
        self.app.testing = False
        self.app.config["PROPAGATE_EXCEPTIONS"] = False
        r = self.get("/api/exit")
        self.assertEqual(r.status_code, 500)
        self.assertFalse(r.get_json()["ok"])


if __name__ == "__main__":
    unittest.main()
