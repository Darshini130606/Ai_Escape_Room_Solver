"""Tests for the three puzzle solvers (no Flask involved)."""
import unittest

from backend import maze_solver, safe_solver, switch_solver
from backend.maze_solver import MAZE, ALGORITHMS, solve, validate_path


class MazeDataTests(unittest.TestCase):
    def test_layout_is_valid(self):
        self.assertEqual(MAZE.rows, 9)
        self.assertEqual(MAZE.cols, 9)
        for row in MAZE.layout:
            self.assertEqual(len(row), 9)
        self.assertEqual(sum(r.count("S") for r in MAZE.layout), 1)
        self.assertEqual(sum(r.count("K") for r in MAZE.layout), 1)
        self.assertEqual(sum(r.count("E") for r in MAZE.layout), 1)
        self.assertGreaterEqual(sum(r.count("H") for r in MAZE.layout), 1)
        # the outer border is solid wall
        self.assertTrue(all(ch == "#" for ch in MAZE.layout[0] + MAZE.layout[-1]))
        self.assertTrue(all(r[0] == "#" and r[-1] == "#" for r in MAZE.layout))


class MazeSolverTests(unittest.TestCase):
    def test_every_algorithm_finds_a_legal_route(self):
        for alg in ALGORITHMS:
            with self.subTest(alg=alg):
                r = solve(alg)
                self.assertTrue(r["found"])
                ok, why = validate_path(r["path"])
                self.assertTrue(ok, why)
                self.assertEqual(r["moves"], len(r["path"]) - 1)

    def test_keycard_comes_before_exit(self):
        for alg in ALGORITHMS:
            r = solve(alg)
            idx = r["key_index"]
            self.assertIsNotNone(idx)
            self.assertEqual(tuple(r["path"][idx]), MAZE.key)
            self.assertEqual(tuple(r["path"][-1]), MAZE.exit)
            self.assertNotIn(list(MAZE.exit), r["path"][:idx + 1])

    def test_ucs_and_astar_are_cheapest(self):
        costs = {a: solve(a)["cost"] for a in ALGORITHMS}
        self.assertEqual(costs["ucs"], costs["astar"])
        self.assertEqual(costs["astar"], 22)
        self.assertLessEqual(costs["astar"], costs["bfs"])
        self.assertLessEqual(costs["astar"], costs["dfs"])

    def test_astar_expands_fewer_states_than_ucs(self):
        self.assertLess(solve("astar")["expanded"], solve("ucs")["expanded"])

    def test_bfs_minimises_moves_but_not_cost(self):
        bfs, ucs = solve("bfs"), solve("ucs")
        self.assertLessEqual(bfs["moves"], ucs["moves"])
        self.assertGreater(bfs["cost"], ucs["cost"])          # weighted hazards fool BFS
        self.assertGreater(bfs["hazards"], 0)
        self.assertTrue(any("does not minimise cost" in m for m in bfs["messages"]))

    def test_cost_matches_tile_costs(self):
        for alg in ALGORITHMS:
            r = solve(alg)
            expected = sum(maze_solver.HAZARD_COST if MAZE.is_hazard(*p) else 1 for p in r["path"][1:])
            self.assertEqual(r["cost"], expected)
            self.assertEqual(r["hazards"], sum(1 for p in r["path"][1:] if MAZE.is_hazard(*p)))

    def test_solve_from_the_middle_with_key(self):
        r = solve("astar", (5, 3), True)
        self.assertTrue(r["found"])
        self.assertEqual(r["moves"], 10)
        self.assertIsNone(r["key_index"])

    def test_unreachable_goal_is_reported(self):
        walled = ["#######", "#S#K.E#", "#######"]
        maze = maze_solver.Maze(walled)
        r = solve("astar", maze=maze)
        self.assertFalse(r["found"])
        self.assertEqual(r["path"], [])
        self.assertEqual(r["headline"], "No route found")
        for alg in ALGORITHMS:
            self.assertFalse(solve(alg, maze=maze)["found"])

    def test_invalid_requests(self):
        with self.assertRaises(maze_solver.MazeError):
            solve("dijkstra")
        with self.assertRaises(maze_solver.MazeError):
            solve("astar", (0, 0))                              # a wall
        with self.assertRaises(maze_solver.MazeError):
            solve("astar", MAZE.exit, False)                    # locked door

    def test_validate_path_rejects_cheating(self):
        self.assertFalse(validate_path([])[0])
        self.assertFalse(validate_path([[1, 7], [1, 1]])[0])    # jump
        self.assertFalse(validate_path([[1, 7], [1, 6], [1, 5], [1, 4], [1, 3], [1, 2], [1, 1]])[0])  # no key


class SafeSolverTests(unittest.TestCase):
    def test_solver_finds_one_unique_code(self):
        r = safe_solver.solve()
        self.assertTrue(r["found"])
        self.assertTrue(r["unique"])
        self.assertEqual(r["solutions"], ["042"])

    def test_solver_agrees_with_brute_force(self):
        brute = ["%03d" % n for n in range(1000) if not safe_solver.broken_clues([int(c) for c in "%03d" % n])]
        self.assertEqual(brute, safe_solver.solve()["solutions"])

    def test_search_trace_has_the_expected_step_kinds(self):
        kinds = {s["kind"] for s in safe_solver.solve()["steps"]}
        self.assertTrue({"Try", "Remove", "Dead end", "Solved"} <= kinds)

    def test_correct_and_wrong_codes(self):
        self.assertTrue(safe_solver.check_code("042")["correct"])
        wrong = safe_solver.check_code("123")
        self.assertFalse(wrong["correct"])
        self.assertEqual(wrong["broken"], [1, 3, 4, 5, 6])
        self.assertIn("breaks clues 1, 3, 4, 5 and 6", safe_solver.describe_broken("123", wrong["broken"]))

    def test_malformed_codes(self):
        for bad in ["", "12", "1234", "abc", "04 ", "０４２", None, 42, ["0", "4", "2"], "-12"]:
            with self.subTest(code=bad):
                with self.assertRaises(safe_solver.SafeError):
                    safe_solver.check_code(bad)

    def test_hints_do_not_leak_the_full_code(self):
        for level in range(4):
            self.assertNotIn("042", safe_solver.hint_for_level(level))


class SwitchSolverTests(unittest.TestCase):
    ALL_ON = {"A": True, "B": True, "C": True}

    def test_all_on_matches_the_design(self):
        ev = switch_solver.evaluate(self.ALL_ON, True, True)
        self.assertEqual([f["rule"] for f in ev["fired"]], ["R1", "R2", "R3", "R4", "R5", "R6"])
        self.assertEqual(ev["conflicts"], ["short_circuit"])
        self.assertFalse(ev["success"])
        self.assertEqual(ev["verdict"]["title"], "Exit blocked")
        self.assertEqual(ev["stats"]["switches_on"], 3)

    def test_exactly_one_valid_setting(self):
        valid = switch_solver.all_valid_configs()
        self.assertEqual(valid, [{"A": True, "B": True, "C": False}])
        r = switch_solver.solve()
        self.assertTrue(r["found"] and r["unique"])
        self.assertEqual(r["solution"], {"A": True, "B": True, "C": False})

    def test_every_other_setting_is_rejected(self):
        from itertools import product
        for values in product([False, True], repeat=3):
            cfg = dict(zip("ABC", values))
            ev = switch_solver.evaluate(cfg, True, True)
            self.assertEqual(ev["success"], cfg == {"A": True, "B": True, "C": False}, cfg)

    def test_prerequisites_matter(self):
        good = {"A": True, "B": True, "C": False}
        self.assertFalse(switch_solver.evaluate(good, False, True)["success"])
        self.assertFalse(switch_solver.evaluate(good, True, False)["success"])
        self.assertEqual(switch_solver.solve(False, True)["found"], False)

    def test_backward_chaining_proof(self):
        ev = switch_solver.evaluate({"A": False, "B": True, "C": False}, True, True)
        self.assertFalse(ev["proof"]["proved"])
        self.assertIn("switch_A_on", [l["fact"] for l in ev["proof"]["lines"] if l["status"] == "missing"])
        ok = switch_solver.evaluate({"A": True, "B": True, "C": False}, True, True)
        self.assertTrue(ok["proof"]["proved"])

    def test_config_validation(self):
        for bad in [None, [], {"A": True}, {"A": True, "B": True, "C": "on"},
                    {"A": True, "B": True, "C": True, "D": True}, {"A": 1, "B": 0, "C": 1}]:
            with self.subTest(cfg=bad):
                with self.assertRaises(switch_solver.SwitchError):
                    switch_solver.validate_config(bad)

    def test_hint_for_the_conflict(self):
        self.assertIn("Turn switch C off", switch_solver.hint(self.ALL_ON, True, True))


if __name__ == "__main__":
    unittest.main()
