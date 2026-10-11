"""The single source of truth for the whole game (kept in memory, one player).

Every rule lives here.  The browser only sends *requests* ("move up", "try 042", "flip switch B");
this module decides whether they are allowed and what changes.
"""
from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional

from . import maze_solver, safe_solver, switch_solver
from .maze_solver import DIRECTION_BY_NAME, MAZE, MazeError
from .safe_solver import SafeError
from .switch_solver import SwitchError

ROOMS = [
    {"id": 1, "name": "Maze", "title": "Room 1: Maze",
     "blurb": ("The exit is in sight but locked. Find the keycard first, then get out. "
               "Laser grids are walkable, but every step on one costs 5.")},
    {"id": 2, "name": "Safe code", "title": "Room 2: Safe code",
     "blurb": ("Seven clues describe a 3-digit code. Each test code tells you how many of its digits "
               "are right. Leading zeros count.")},
    {"id": 3, "name": "Switches", "title": "Room 3: Switches",
     "blurb": ("Light the exit lamp. Each switch changes what the rules can prove, and the keycard "
               "note says something about switch C.")},
    {"id": 4, "name": "Exit", "title": "Final exit",
     "blurb": "The final door checks everything you have collected and every puzzle you have solved."},
]
ROOM_LABELS = {"complete": "Done", "active": "In progress", "available": "Ready", "locked": "Locked"}

ITEMS = {
    "keycard": {"name": "Keycard", "room": 1, "icon": "/assets/keycard.svg",
                "inspect": "A magnetic keycard. A note on the back reads: \"%s\"" % switch_solver.KEYCARD_NOTE},
    "chip": {"name": "Access chip", "room": 2, "icon": "/assets/chip.svg",
             "inspect": "A small access chip taken from the safe. The exit door's reader accepts it."},
}

LOG_LIMIT = 300


class GameError(Exception):
    """A request the game refuses. ``status`` is the HTTP status the API should answer with."""

    def __init__(self, message: str, status: int = 400, extra: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.extra = extra or {}


class Game:
    def __init__(self):
        self._lock = threading.RLock()
        self.reset()

    # ==================================================================
    # Lifecycle
    # ==================================================================
    def reset(self) -> None:
        with self._lock:
            self.started_at = time.monotonic()
            self.finished_at: Optional[float] = None
            self.current_room = 1
            self.completed = set()          # room ids: 1, 2, 3
            self.mission_complete = False
            self.inventory: List[str] = []
            self.moves = 0
            self.hints = 0
            self.hint_levels = {1: 0, 2: 0, 3: 0}
            self.hint = None                # {"room": n, "text": str}
            self.log: List[dict] = []
            self.output = {"level": "info", "text": "Game initialized. Find the keycard and reach the exit door."}
            self.ai: Dict[int, dict] = {}   # last solver result per room

            # room 1
            self.maze_pos = MAZE.start
            self.maze_trail = [list(MAZE.start)]
            self.maze_steps = 0
            self.maze_cost = 0
            self.hazards_crossed = 0
            self.algorithm = "astar"
            self.last_route: Optional[dict] = None

            # room 2
            self.clues_read = False
            self.safe_tries: List[dict] = []
            self.safe_unlocked = False
            self.code_found_by_solver = False

            # room 3
            self.switches = {name: True for name in switch_solver.SWITCHES}
            self.power_restored = False
            self.switch_checks = 0

            self._log("info", "Game initialized.")
            self._log("info", "Maze loaded: %d x %d tiles, start (%d, %d)." % (
                MAZE.rows, MAZE.cols, MAZE.start[0], MAZE.start[1]))

    # ==================================================================
    # Small helpers
    # ==================================================================
    def elapsed(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return max(0.0, end - self.started_at)

    def _log(self, level: str, text: str) -> None:
        secs = int(self.elapsed())
        self.log.append({"time": "%02d:%02d" % (secs // 60, secs % 60), "level": level, "text": text})
        if len(self.log) > LOG_LIMIT:
            del self.log[: len(self.log) - LOG_LIMIT]

    def _say(self, level: str, text: str, log: bool = True) -> None:
        self.output = {"level": level, "text": text}
        if log:
            self._log(level, text)

    def has(self, item: str) -> bool:
        return item in self.inventory

    def _add_item(self, item: str) -> None:
        if item not in self.inventory:
            self.inventory.append(item)

    def is_available(self, room: int) -> bool:
        if room == 1:
            return True
        if room in (2, 3):
            return (room - 1) in self.completed
        if room == 4:
            return 3 in self.completed
        return False

    def room_status(self, room: int) -> str:
        done = (room == 4 and self.mission_complete) or room in self.completed
        if done:
            return "complete"
        if not self.is_available(room):
            return "locked"
        return "active" if room == self.current_room else "available"

    def _require_room(self, room: int) -> None:
        if not self.is_available(room):
            raise GameError(self._locked_message(room), 403)

    def _locked_message(self, room: int) -> str:
        if room == 4:
            unmet = [r["label"] for r in self.exit_requirements() if not r["met"]]
            return "The exit is locked. Still needed: %s." % "; ".join(unmet)
        return "Room %d is locked. Finish Room %d first." % (room, room - 1)

    def _count_move(self) -> None:
        self.moves += 1

    # ==================================================================
    # Navigation
    # ==================================================================
    def navigate(self, room) -> dict:
        with self._lock:
            if isinstance(room, bool) or not isinstance(room, int) or room not in (1, 2, 3, 4):
                raise GameError("Choose a room from 1 to 4.", 400)
            if self.mission_complete:
                raise GameError("The mission is complete. Restart to play again.", 409)
            if not self.is_available(room):
                msg = self._locked_message(room)
                self._say("error", msg)
                raise GameError(msg, 403)
            self.current_room = room
            return self.to_dict()

    # ==================================================================
    # Room 1: maze
    # ==================================================================
    def _maze_open(self) -> None:
        if 1 in self.completed:
            raise GameError("The maze is already complete.", 409)

    def set_algorithm(self, algorithm) -> dict:
        with self._lock:
            if algorithm not in maze_solver.ALGORITHMS:
                raise GameError("Unknown algorithm. Choose one of: %s." % ", ".join(maze_solver.ALGORITHMS), 400)
            self.algorithm = algorithm
            self._log("info", "Search algorithm selected: %s." % maze_solver.ALGORITHM_INFO[algorithm]["label"])
            return self.to_dict()

    def maze_solve(self, algorithm=None) -> dict:
        with self._lock:
            algorithm = algorithm or self.algorithm
            try:
                result = maze_solver.solve(algorithm, self.maze_pos, self.has("keycard"))
            except MazeError as exc:
                raise GameError(str(exc), 400)
            self.algorithm = algorithm
            self.ai[1] = result
            self._log("info", "%s search started from (%d, %d)%s." % (
                result["label"], self.maze_pos[0], self.maze_pos[1],
                " with the keycard" if self.has("keycard") else ""))
            if result["found"]:
                self._say("success", "%s found a route: %d moves, cost %d, %d states expanded." % (
                    result["label"], result["moves"], result["cost"], result["expanded"]))
            else:
                self._say("error", "%s found no route to the exit." % result["label"])
            return result

    def _step(self, direction: str) -> None:
        """Apply one maze step. Raises GameError for illegal moves. Caller holds the lock."""
        if direction not in DIRECTION_BY_NAME:
            raise GameError("Direction must be up, down, left or right.", 400)
        dr, dc = DIRECTION_BY_NAME[direction]
        r, c = self.maze_pos[0] + dr, self.maze_pos[1] + dc
        if MAZE.is_wall(r, c):
            raise GameError("A wall blocks the way.", 409)
        if (r, c) == MAZE.exit and not self.has("keycard"):
            raise GameError("The exit door is locked. Collect the keycard first.", 409)
        self.maze_pos = (r, c)
        self.maze_trail.append([r, c])
        self.maze_steps += 1
        self.maze_cost += MAZE.step_cost(r, c)
        self._count_move()
        if MAZE.is_hazard(r, c):
            self.hazards_crossed += 1
            self._say("error", "Laser grid at (%d, %d): that step cost 5." % (r, c))
        if (r, c) == MAZE.key and not self.has("keycard"):
            self._add_item("keycard")
            self._say("success", "Keycard collected at (%d, %d)." % (r, c))
        if (r, c) == MAZE.exit and self.has("keycard"):
            self._complete_maze()

    def maze_move(self, direction) -> dict:
        with self._lock:
            self._maze_open()
            if not isinstance(direction, str):
                raise GameError("Send a direction: up, down, left or right.", 400)
            before = self.output
            try:
                self._step(direction)
            except GameError as exc:
                if exc.status == 409:
                    self._say("error", exc.message)
                raise
            if self.output is before:
                self._say("info", "Moved %s to (%d, %d)." % (direction, self.maze_pos[0], self.maze_pos[1]),
                          log=False)
            return self.to_dict()

    def maze_apply(self, algorithm=None) -> dict:
        """Let the AI walk its route. The server re-solves; it never trusts a path from the browser."""
        with self._lock:
            self._maze_open()
            result = self.maze_solve(algorithm)
            if not result["found"]:
                raise GameError("There is no route to apply.", 409)
            path = result["path"]
            self._log("info", "Applying the %s route: %d moves." % (result["label"], result["moves"]))
            for (r0, c0), (r1, c1) in zip(path, path[1:]):
                direction = next(n for dr, dc, n in maze_solver.DIRECTIONS if (r0 + dr, c0 + dc) == (r1, c1))
                self._step(direction)
            self.last_route = {"algorithm": result["algorithm"], "moves": result["moves"], "cost": result["cost"]}
            if 1 in self.completed:
                self._say("success", "The %s route was walked in %d moves. Exit door opened: Room 2 is unlocked."
                          % (result["label"], result["moves"]))
            return self.to_dict()

    def maze_complete(self) -> dict:
        """Explicit completion check. Only succeeds when the player truly holds the keycard at the exit."""
        with self._lock:
            if 1 in self.completed:
                return {"completed": True, "already": True, "message": "The maze is already complete."}
            if not self.has("keycard"):
                raise GameError("You still need the keycard before the exit will open.", 403)
            if self.maze_pos != MAZE.exit:
                raise GameError("You are not standing at the exit door yet.", 403)
            self._complete_maze()
            return {"completed": True, "already": False, "message": self.output["text"]}

    def _complete_maze(self) -> None:
        if 1 in self.completed:
            return
        self.completed.add(1)
        self.current_room = 2
        self._say("success", "Exit door opened. Room 1 complete: Room 2 is unlocked.")

    # ==================================================================
    # Room 2: safe code
    # ==================================================================
    def _mark_clues_read(self) -> None:
        if not self.clues_read:
            self.clues_read = True
            self._log("info", "Clues inspected: seven clues describe the %d-digit safe code." %
                      safe_solver.CODE_LENGTH)

    def safe_clues(self) -> dict:
        with self._lock:
            self._require_room(2)
            self._mark_clues_read()
            return {"clues": safe_solver.public_clues(), "code_length": safe_solver.CODE_LENGTH}

    def safe_solve(self) -> dict:
        with self._lock:
            self._require_room(2)
            self._mark_clues_read()
            result = safe_solver.solve()
            self.code_found_by_solver = True
            self.ai[2] = result
            self._log("info", "Backtracking search finished: %d solution(s), %d backtracks." % (
                result["stats"]["solutions"], result["stats"]["backtracks"]))
            self._say("success", "The solver found the code: %s." % result["solution"]
                      if result["found"] else "The solver found no code.")
            return result

    def safe_check(self, code) -> dict:
        with self._lock:
            self._require_room(2)
            if self.safe_unlocked:
                return {"correct": True, "already": True, "code": None, "broken": [],
                        "message": "The safe is already open."}
            try:
                verdict = safe_solver.check_code(code)
            except SafeError as exc:
                self._say("error", str(exc), log=False)
                raise GameError(str(exc), 400)
            self._mark_clues_read()
            self._count_move()
            digits = verdict["code"]
            self.safe_tries.append({"code": digits, "broken": verdict["broken"],
                                    "message": safe_solver.describe_broken(digits, verdict["broken"])})
            self._log("info", "Safe code submitted: %s." % digits)
            if verdict["correct"]:
                self.safe_unlocked = True
                self._add_item("chip")
                self.completed.add(2)
                self.current_room = 3
                verdict["message"] = "The safe opens. You take the access chip. Room 3 is unlocked."
                self._say("success", "Safe unlocked with %s. Access chip collected." % digits)
                self._log("success", "Room 2 complete: Room 3 is unlocked.")
            else:
                verdict["message"] = safe_solver.describe_broken(digits, verdict["broken"])
                self._say("error", "Code %s rejected. %s" % (digits, verdict["message"]))
            verdict["already"] = False
            return verdict

    def safe_apply(self) -> dict:
        with self._lock:
            self._require_room(2)
            result = self.safe_solve()
            if not result["found"] or not result["unique"]:
                raise GameError("The solver could not find one single code.", 409)
            return self.safe_check(result["solution"])

    # ==================================================================
    # Room 3: switches
    # ==================================================================
    def _evaluation(self) -> dict:
        return switch_solver.evaluate(self.switches, self.has("keycard"), self.safe_unlocked)

    def switches_state(self) -> dict:
        with self._lock:
            self._require_room(3)
            return self._switch_payload()

    def _switch_payload(self) -> dict:
        return {"config": dict(self.switches), "evaluation": self._evaluation(),
                "power_restored": self.power_restored, "note": switch_solver.KEYCARD_NOTE}

    def switch_toggle(self, name) -> dict:
        with self._lock:
            self._require_room(3)
            if self.power_restored:
                raise GameError("Power is already restored. The switches are locked.", 409)
            if name not in switch_solver.SWITCHES:
                raise GameError("There is no switch '%s'. Use A, B or C." % (name,), 400)
            self.switches[name] = not self.switches[name]
            self._count_move()
            self._log("info", "Switch %s turned %s." % (name, "on" if self.switches[name] else "off"))
            return self._switch_payload()

    def switch_check(self, config=None) -> dict:
        with self._lock:
            self._require_room(3)
            if self.power_restored:
                payload = self._switch_payload()
                payload["message"] = "Power is already restored."
                payload["already"] = True
                return payload
            if config is not None:
                try:
                    self.switches = switch_solver.validate_config(config)
                except SwitchError as exc:
                    raise GameError(str(exc), 400)
            self._count_move()
            self.switch_checks += 1
            evaluation = self._evaluation()
            self._log("info", "Switch configuration checked: A %s, B %s, C %s." % tuple(
                "on" if self.switches[n] else "off" for n in switch_solver.SWITCHES))
            if evaluation["success"]:
                self.power_restored = True
                self.completed.add(3)
                self.current_room = 4
                self._say("success", "Power restored. The exit light is on. Room 3 complete: the exit can be checked.")
            else:
                verdict = evaluation["verdict"]
                self._say("error", "%s. %s" % (verdict["title"], verdict["text"]))
            payload = self._switch_payload()
            payload["message"] = self.output["text"]
            payload["already"] = False
            return payload

    def switch_solve(self) -> dict:
        with self._lock:
            self._require_room(3)
            result = switch_solver.solve(self.has("keycard"), self.safe_unlocked)
            self.ai[3] = result
            self._log("info", "Rule solver checked all %d switch settings: %d valid." % (
                result["checked"], result["valid_count"]))
            self._say("success" if result["found"] else "error", result["headline"] + ".")
            return result

    def switch_apply(self) -> dict:
        with self._lock:
            self._require_room(3)
            if self.power_restored:
                return self.switch_check()
            result = self.switch_solve()
            if not result["found"]:
                raise GameError("The solver found no valid setting.", 409)
            return self.switch_check(result["solution"])

    # ==================================================================
    # Exit
    # ==================================================================
    def exit_requirements(self) -> List[dict]:
        return [
            {"id": "maze", "label": "Escape the maze (Room 1)", "met": 1 in self.completed},
            {"id": "keycard", "label": "Hold the keycard", "met": self.has("keycard")},
            {"id": "safe", "label": "Open the safe (Room 2)", "met": self.safe_unlocked and 2 in self.completed},
            {"id": "chip", "label": "Hold the access chip", "met": self.has("chip")},
            {"id": "power", "label": "Restore the power (Room 3)", "met": self.power_restored and 3 in self.completed},
        ]

    def exit_status(self) -> dict:
        with self._lock:
            reqs = self.exit_requirements()
            return {"requirements": reqs, "all_met": all(r["met"] for r in reqs),
                    "complete": self.mission_complete}

    def exit_open(self) -> dict:
        with self._lock:
            if self.mission_complete:
                return dict(self.exit_status(), already=True, message="You already escaped.")
            reqs = self.exit_requirements()
            unmet = [r["label"] for r in reqs if not r["met"]]
            if unmet:
                self._say("error", "Exit requirements not met: %s." % "; ".join(unmet))
                raise GameError("The exit is locked. Still needed: %s." % "; ".join(unmet), 403,
                                {"requirements": reqs})
            self._log("success", "Exit requirements verified.")
            self.mission_complete = True
            self.finished_at = time.monotonic()
            self.current_room = 4
            self._say("success", "Mission completed. You escaped!")
            return dict(self.exit_status(), already=False, message=self.output["text"])

    # ==================================================================
    # Hints and inspection
    # ==================================================================
    def give_hint(self) -> dict:
        with self._lock:
            if self.mission_complete:
                raise GameError("The mission is complete. Restart to play again.", 409)
            room = self.current_room
            if room == 1:
                route = maze_solver.solve("astar", self.maze_pos, self.has("keycard"))
                if route["found"] and route["moves"] > 0:
                    nr, nc = route["path"][1]
                    direction = next(n for dr, dc, n in maze_solver.DIRECTIONS
                                     if (self.maze_pos[0] + dr, self.maze_pos[1] + dc) == (nr, nc))
                    goal = "exit" if self.has("keycard") else "keycard"
                    text = "Go %s first. The cheapest way to the %s from here is %d moves and crosses %d laser grid(s)." % (
                        direction, goal, route["moves"], route["hazards"])
                else:
                    text = "No route is open from here. Restart if you are stuck."
            elif room == 2:
                text = safe_solver.hint_for_level(self.hint_levels[2])
            elif room == 3:
                text = switch_solver.hint(self.switches, self.has("keycard"), self.safe_unlocked)
            else:
                unmet = [r["label"] for r in self.exit_requirements() if not r["met"]]
                text = ("Everything is in place. Open the exit door." if not unmet
                        else "Still needed: %s." % "; ".join(unmet))
            self.hint_levels[room] = self.hint_levels.get(room, 0) + 1
            self.hints += 1
            self.hint = {"room": room, "text": text}
            self._say("info", "AI hint: %s" % text)
            return self.hint

    def inspect(self, item) -> dict:
        with self._lock:
            if item not in ITEMS:
                raise GameError("Unknown item.", 400)
            if not self.has(item):
                raise GameError("You have not collected that item yet.", 403)
            text = ITEMS[item]["inspect"]
            self._say("info", "Inspected %s. %s" % (ITEMS[item]["name"], text))
            return {"item": item, "name": ITEMS[item]["name"], "text": text}

    # ==================================================================
    # Objectives and progress
    # ==================================================================
    def objectives(self) -> List[dict]:
        def obj(oid, room, label, done, optional=False, missed=False):
            return {"id": oid, "room": room, "label": label, "done": bool(done),
                    "optional": optional, "missed": bool(missed)}

        solver_code = self.code_found_by_solver or self.safe_unlocked
        return [
            obj("keycard", 1, "Collect the keycard", self.has("keycard")),
            obj("maze_exit", 1, "Reach the exit door", 1 in self.completed),
            obj("avoid_lasers", 1, "Avoid laser grids where you can",
                1 in self.completed and self.hazards_crossed == 0, optional=True,
                missed=self.hazards_crossed > 0),
            obj("read_clues", 2, "Read the seven clues", self.clues_read),
            obj("find_code", 2, "Find the 3-digit code", solver_code),
            obj("open_safe", 2, "Open the safe", self.safe_unlocked),
            obj("exit_light", 3, "Turn the exit light on", self.power_restored),
            obj("no_short", 3, "Avoid a short circuit", self.power_restored),
            obj("escape", 4, "Open the exit door", self.mission_complete),
        ]

    def progress_percent(self) -> int:
        required = [o for o in self.objectives() if not o["optional"]]
        done = sum(1 for o in required if o["done"])
        return int(round(100 * done / len(required)))

    def knowledge(self) -> List[str]:
        facts = [
            "Floor tiles cost 1 per step. Laser grids are walkable but cost 5 per step.",
            "The maze exit stays locked until you hold the keycard.",
        ]
        route = self.ai.get(1)
        if route and route["found"]:
            facts.append("%s found a route of %d moves with cost %d (cheapest possible: %s)." % (
                route["label"], route["moves"], route["cost"], route["optimal_cost"]))
        if self.has("keycard"):
            facts.append("You hold the keycard: it is needed for the exit and for Room 3's power rule R1.")
        if self.is_available(2):
            facts.append("The safe code has %d digits, each from 0 to 9, and leading zeros count." %
                         safe_solver.CODE_LENGTH)
            if self.clues_read:
                for clue in safe_solver.CLUES:
                    if clue["kind"] == "match" and clue["placed"] + clue["misplaced"] == 0:
                        facts.append("Clue %d says none of the digits %s is in the code." % (
                            clue["id"], ", ".join(str(d) for d in clue["guess"])))
            for t in self.safe_tries[-3:]:
                facts.append("Tried %s: %s" % (t["code"], t["message"]))
            if self.code_found_by_solver and not self.safe_unlocked:
                facts.append("The solver reports that exactly one code obeys all the clues.")
        if self.safe_unlocked:
            facts.append("The safe is open. It held the access chip.")
        if self.is_available(3):
            facts.append("Keycard note: %s" % switch_solver.KEYCARD_NOTE)
            for rule in switch_solver.RULES:
                facts.append("%s: if %s then %s." % (rule["id"], " and ".join(rule["premises"]), rule["conclusion"]))
        if self.power_restored:
            facts.append("Working setting: %s." % ", ".join(
                "switch %s %s" % (n, "on" if self.switches[n] else "off") for n in switch_solver.SWITCHES))
        return facts

    def _agent(self) -> dict:
        room = self.current_room
        inv = [ITEMS[i]["name"] for i in self.inventory] or ["nothing yet"]
        ai = self.ai.get(room)
        if self.mission_complete:
            status, nxt = "Escaped", "Press Restart to play again."
        elif room == 1:
            status = "Keycard collected, exit still locked" if self.has("keycard") else "Looking for the keycard"
            if ai and ai.get("found"):
                nxt = "Press Apply AI solution to walk the %s route (%d moves)." % (ai["label"], ai["moves"])
            else:
                nxt = "Pick an algorithm and press AI solve, or move yourself with the arrows."
        elif room == 2:
            status = "Safe open" if self.safe_unlocked else "%d code(s) tried" % len(self.safe_tries)
            if self.code_found_by_solver and not self.safe_unlocked:
                nxt = "Press Apply AI solution to enter the code the solver found."
            else:
                nxt = "Compare the clues and try a code, or press AI solve."
        elif room == 3:
            ev = self._evaluation()
            status = "Power restored" if self.power_restored else ev["verdict"]["title"]
            nxt = ("Open the exit door." if self.power_restored
                   else "Read which rules fire, then press Evaluate switches.")
        else:
            reqs = [r for r in self.exit_requirements() if not r["met"]]
            status = "Ready to escape" if not reqs else "Locked"
            nxt = "Open the exit door." if not reqs else "Finish: %s." % "; ".join(r["label"] for r in reqs)
        algo = None
        if room == 1:
            algo = maze_solver.ALGORITHM_INFO[self.algorithm]["title"]
        elif room == 2:
            algo = "Backtracking with forward checking"
        elif room == 3:
            algo = "Forward chaining"
        return {
            "room": room,
            "room_name": ROOMS[room - 1]["title"],
            "status": status,
            "algorithm": algo,
            "inventory": inv,
            "next_action": nxt,
            "last_result": (ai.get("headline") + ": " + ai["messages"][0] if ai and ai.get("messages")
                            else (ai.get("headline") if ai else "No solver has run in this room yet.")),
        }

    # ==================================================================
    # Serialisation
    # ==================================================================
    def mission_status(self) -> str:
        if self.mission_complete:
            return "Escaped"
        return "In progress"

    def to_dict(self) -> dict:
        with self._lock:
            rooms = []
            for room in ROOMS:
                status = self.room_status(room["id"])
                rooms.append({"id": room["id"], "name": room["name"], "title": room["title"], "blurb": room["blurb"],
                              "status": status, "label": ROOM_LABELS[status],
                              "available": self.is_available(room["id"])})
            inventory = []
            for key, item in ITEMS.items():
                got = self.has(key)
                if got:
                    detail = "Collected in Room %d" % item["room"]
                elif key == "keycard":
                    detail = "Not collected yet"
                else:
                    detail = "Inside the safe" if self.is_available(2) else "Found in Room 2"
                inventory.append({"id": key, "name": item["name"], "collected": got, "detail": detail,
                                  "icon": item["icon"]})

            state = {
                "current_room": self.current_room,
                "rooms": rooms,
                "mission": {"complete": self.mission_complete, "status": self.mission_status(),
                            "progress": self.progress_percent(),
                            "rooms_done": len(self.completed) + (1 if self.mission_complete else 0)},
                "stats": {"moves": self.moves, "hints": self.hints, "elapsed": round(self.elapsed(), 1),
                          "running": not self.mission_complete},
                "inventory": inventory,
                "objectives": self.objectives(),
                "maze": {
                    "layout": MAZE.to_rows(), "rows": MAZE.rows, "cols": MAZE.cols,
                    "start": list(MAZE.start), "key": list(MAZE.key), "exit": list(MAZE.exit),
                    "pos": list(self.maze_pos), "has_key": self.has("keycard"),
                    "complete": 1 in self.completed, "steps": self.maze_steps, "cost": self.maze_cost,
                    "hazards_crossed": self.hazards_crossed, "trail": self.maze_trail,
                    "algorithm": self.algorithm, "hazard_cost": maze_solver.HAZARD_COST,
                    "algorithms": [{"id": a, "label": maze_solver.ALGORITHM_INFO[a]["label"],
                                    "title": maze_solver.ALGORITHM_INFO[a]["title"],
                                    "tag": maze_solver.ALGORITHM_INFO[a]["tag"],
                                    "text": maze_solver.ALGORITHM_INFO[a]["text"]}
                                   for a in maze_solver.ALGORITHMS],
                },
                "safe": {"available": self.is_available(2), "unlocked": self.safe_unlocked,
                         "code_length": safe_solver.CODE_LENGTH, "tries": list(self.safe_tries),
                         "clues_read": self.clues_read,
                         "clues": safe_solver.public_clues() if self.is_available(2) else [],
                         "info": {"title": "Backtracking", "tag": "with forward checking",
                                  "text": ("A constraint satisfaction problem: each digit is a variable from 0 to 9 "
                                           "and every clue removes digits that break it. The search tries what is "
                                           "left and backs up from dead ends.")}},
                "switches": ({"available": True, **self._switch_payload(), "info": switch_solver.INFO}
                             if self.is_available(3) else
                             {"available": False, "info": switch_solver.INFO}),
                "exit": self.exit_status(),
                "ai": {str(k): v for k, v in self.ai.items()},
                "hint": self.hint,
                "output": self.output,
                "knowledge": self.knowledge(),
                "agent": self._agent(),
                "log": list(self.log),
            }
            return state
