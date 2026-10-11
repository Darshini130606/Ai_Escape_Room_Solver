"""Room 1 - the laser maze and its search algorithms.

The maze is plain data (a list of strings).  The solvers search the *state space*
``(row, col, has_key)``, so the route automatically has to visit the keycard
before it is allowed to enter the locked exit door.

Tile legend
    ``#`` wall      ``.`` floor (cost 1)      ``H`` laser grid (cost 5)
    ``S`` start     ``K`` keycard             ``E`` locked exit door
"""
from __future__ import annotations

import heapq
from collections import deque
from typing import Dict, List, Optional, Tuple

MAZE_LAYOUT: List[str] = [
    "#########",
    "#E.....S#",
    "###.#.#H#",
    "#...#...#",
    "#.#####H#",
    "#..K..H.#",
    "#.###.#.#",
    "#H.....H#",
    "#########",
]

FLOOR_COST = 1
HAZARD_COST = 5

# (row delta, col delta, name) - the order is also the tie-break order of the searches.
DIRECTIONS: List[Tuple[int, int, str]] = [
    (-1, 0, "up"),
    (1, 0, "down"),
    (0, -1, "left"),
    (0, 1, "right"),
]
DIRECTION_BY_NAME = {name: (dr, dc) for dr, dc, name in DIRECTIONS}

ALGORITHMS = ("bfs", "dfs", "ucs", "astar")

ALGORITHM_INFO: Dict[str, Dict[str, str]] = {
    "bfs": {
        "label": "BFS",
        "title": "Breadth-first search",
        "tag": "fewest moves",
        "text": (
            "BFS explores the maze in rings: every state one move away, then every state two moves "
            "away, and so on. On a grid where every step is equal it finds the route with the fewest "
            "moves. Laser grids cost more, but BFS ignores costs, so its route can be shorter in moves "
            "and still more expensive in cost."
        ),
    },
    "dfs": {
        "label": "DFS",
        "title": "Depth-first search",
        "tag": "go deep, back up",
        "text": (
            "DFS follows one corridor as far as it can and only backs up at a dead end. It finds a route "
            "quickly and uses little memory, but the route is not guaranteed to be short or cheap."
        ),
    },
    "ucs": {
        "label": "UCS",
        "title": "Uniform-cost search",
        "tag": "lowest g(n) first",
        "text": (
            "UCS always expands the state with the lowest cost paid so far, g(n). Because laser grids "
            "cost 5 and floor costs 1, it returns the cheapest route. It has no sense of direction, so "
            "it expands more states than A*."
        ),
    },
    "astar": {
        "label": "A*",
        "title": "A* Search",
        "tag": "f(n) = g(n) + h(n)",
        "text": (
            "A* always expands the state with the lowest f(n). g(n) is the cost paid so far. h(n) is the "
            "distance still to go: to the keycard, then from the keycard to the exit. It never "
            "overestimates, so the route it returns is the cheapest."
        ),
    },
}

State = Tuple[int, int, bool]


class MazeError(ValueError):
    """Raised for invalid maze requests (bad algorithm, bad position...)."""


class Maze:
    def __init__(self, layout: List[str]):
        self.layout = list(layout)
        self.rows = len(layout)
        self.cols = len(layout[0]) if layout else 0
        self.start: Optional[Tuple[int, int]] = None
        self.key: Optional[Tuple[int, int]] = None
        self.exit: Optional[Tuple[int, int]] = None
        for r, row in enumerate(layout):
            if len(row) != self.cols:
                raise MazeError("Maze rows must all have the same length.")
            for c, ch in enumerate(row):
                if ch == "S":
                    self.start = (r, c)
                elif ch == "K":
                    self.key = (r, c)
                elif ch == "E":
                    self.exit = (r, c)
        if not (self.start and self.key and self.exit):
            raise MazeError("Maze needs a start, a keycard and an exit.")

    # --- tile helpers -------------------------------------------------
    def tile(self, r: int, c: int) -> str:
        if 0 <= r < self.rows and 0 <= c < self.cols:
            return self.layout[r][c]
        return "#"

    def is_wall(self, r: int, c: int) -> bool:
        return self.tile(r, c) == "#"

    def is_hazard(self, r: int, c: int) -> bool:
        return self.tile(r, c) == "H"

    def step_cost(self, r: int, c: int) -> int:
        return HAZARD_COST if self.is_hazard(r, c) else FLOOR_COST

    # --- state space --------------------------------------------------
    def successors(self, state: State) -> List[Tuple[State, int, str]]:
        """Legal moves from a state as ``(next_state, cost, direction)``."""
        r, c, has_key = state
        out = []
        for dr, dc, name in DIRECTIONS:
            nr, nc = r + dr, c + dc
            if self.is_wall(nr, nc):
                continue
            if (nr, nc) == self.exit and not has_key:
                continue  # the exit door is locked without the keycard
            nkey = has_key or (nr, nc) == self.key
            out.append(((nr, nc, nkey), self.step_cost(nr, nc), name))
        return out

    def is_goal(self, state: State) -> bool:
        return (state[0], state[1]) == self.exit and state[2]

    def heuristic(self, state: State) -> int:
        """Admissible estimate: Manhattan distance via the keycard, then to the exit."""
        r, c, has_key = state
        er, ec = self.exit
        if has_key:
            return abs(r - er) + abs(c - ec)
        kr, kc = self.key
        return abs(r - kr) + abs(c - kc) + abs(kr - er) + abs(kc - ec)

    def to_rows(self) -> List[str]:
        return list(self.layout)


MAZE = Maze(MAZE_LAYOUT)


# ----------------------------------------------------------------------
# Searches
# ----------------------------------------------------------------------
def _rebuild(parents: Dict[State, Optional[State]], goal: State) -> List[State]:
    chain = []
    node: Optional[State] = goal
    while node is not None:
        chain.append(node)
        node = parents[node]
    chain.reverse()
    return chain


def _search(maze: Maze, algorithm: str, start: State):
    """Run one search. Returns (goal_state | None, parents, g_of_state, expansion_log)."""
    parents: Dict[State, Optional[State]] = {start: None}
    g_cost: Dict[State, int] = {start: 0}
    log: List[dict] = []  # one entry per expansion, in order

    def record(state: State, g: int):
        entry = {"state": [state[0], state[1]], "key": state[2], "g": g}
        if algorithm == "astar":
            h = maze.heuristic(state)
            entry["h"] = h
            entry["f"] = g + h
        log.append(entry)

    if algorithm == "bfs":
        frontier = deque([start])
        seen = {start}
        while frontier:
            state = frontier.popleft()
            record(state, g_cost[state])
            if maze.is_goal(state):
                return state, parents, g_cost, log
            for nxt, cost, _ in maze.successors(state):
                if nxt not in seen:
                    seen.add(nxt)
                    parents[nxt] = state
                    g_cost[nxt] = g_cost[state] + cost
                    frontier.append(nxt)
        return None, parents, g_cost, log

    if algorithm == "dfs":
        stack: List[Tuple[State, Optional[State], int]] = [(start, None, 0)]
        closed = set()
        parents = {}
        while stack:
            state, parent, g = stack.pop()
            if state in closed:
                continue
            closed.add(state)
            parents[state] = parent
            g_cost[state] = g
            record(state, g)
            if maze.is_goal(state):
                return state, parents, g_cost, log
            # push in reverse so "up" is explored first
            for nxt, cost, _ in reversed(maze.successors(state)):
                if nxt not in closed:
                    stack.append((nxt, state, g + cost))
        return None, parents, g_cost, log

    # UCS and A* share a priority-queue loop; only the priority differs.
    counter = 0
    heap: List[tuple] = []

    def push(state: State, g: int):
        nonlocal counter
        counter += 1
        h = maze.heuristic(state) if algorithm == "astar" else 0
        heapq.heappush(heap, (g + h, h, counter, state))

    push(start, 0)
    closed = set()
    while heap:
        _, _, _, state = heapq.heappop(heap)
        if state in closed:
            continue
        closed.add(state)
        record(state, g_cost[state])
        if maze.is_goal(state):
            return state, parents, g_cost, log
        for nxt, cost, _ in maze.successors(state):
            ng = g_cost[state] + cost
            if nxt not in g_cost or ng < g_cost[nxt]:
                g_cost[nxt] = ng
                parents[nxt] = state
                push(nxt, ng)
    return None, parents, g_cost, log


def solve(algorithm: str, start: Optional[Tuple[int, int]] = None, has_key: bool = False,
          maze: Maze = MAZE, _with_optimum: bool = True) -> dict:
    """Solve the maze from ``start`` (default: the maze start) with the chosen algorithm."""
    if algorithm not in ALGORITHMS:
        raise MazeError("Unknown algorithm '%s'. Choose one of: %s." % (algorithm, ", ".join(ALGORITHMS)))
    start = start or maze.start
    if (not isinstance(start, tuple) or len(start) != 2 or maze.is_wall(*start)):
        raise MazeError("The start position is not a walkable tile.")
    if start == maze.exit and not has_key:
        raise MazeError("The start position is the locked exit door.")
    has_key = bool(has_key or start == maze.key)
    start_state: State = (start[0], start[1], has_key)

    goal, parents, g_cost, log = _search(maze, algorithm, start_state)
    info = ALGORITHM_INFO[algorithm]
    explored: List[List[int]] = []
    for entry in log:
        if entry["state"] not in explored:
            explored.append(entry["state"])
    result = {
        "algorithm": algorithm,
        "label": info["label"],
        "title": info["title"],
        "tag": info["tag"],
        "explanation": info["text"],
        "start": [start[0], start[1]],
        "had_key": has_key,
        "found": goal is not None,
        "expanded": len(log),
        "trace": log[:8],
        "trace_columns": ["state", "key", "g", "h", "f"] if algorithm == "astar" else ["state", "key", "g"],
        "explored": explored,
        "path": [],
        "moves": 0,
        "cost": 0,
        "hazards": 0,
        "key_index": None,
        "optimal_cost": None,
        "messages": [],
        "level": "error",
        "headline": "",
    }

    if goal is None:
        result["headline"] = "No route found"
        result["messages"] = [
            "%s expanded %d states and could not reach the exit with the keycard." % (info["label"], len(log)),
            "Every route is blocked by walls, or the keycard cannot be reached.",
        ]
        return result

    chain = _rebuild(parents, goal)
    path = [[s[0], s[1]] for s in chain]
    cost = sum(maze.step_cost(r, c) for r, c in path[1:])
    hazards = sum(1 for r, c in path[1:] if maze.is_hazard(r, c))
    key_index = None
    if not has_key:
        for i, s in enumerate(chain):
            if s[2]:
                key_index = i
                break
    result.update(path=path, moves=len(path) - 1, cost=cost, hazards=hazards, key_index=key_index,
                  level="success", headline="Route found")

    if _with_optimum:
        result["optimal_cost"] = cost if algorithm in ("ucs", "astar") else solve(
            "ucs", start, has_key, maze, _with_optimum=False)["cost"]

    msgs = ["Exit reached. Path length %d moves, total cost %d, %d states expanded."
            % (result["moves"], cost, result["expanded"])]
    if key_index is not None:
        kr, kc = path[key_index]
        msgs.append("The keycard is collected at (%d, %d) on move %d, before the exit is entered."
                    % (kr, kc, key_index))
    msgs.append("The path crosses %d hazard tile(s)." % hazards)
    optimum = result["optimal_cost"]
    if optimum is not None and cost > optimum:
        msgs.append("The cheapest possible route costs %d, so this one pays %d extra. %s does not minimise cost."
                    % (optimum, cost - optimum, info["label"]))
    result["messages"] = msgs
    return result


def validate_path(path: List[List[int]], maze: Maze = MAZE) -> Tuple[bool, str]:
    """Check a route against the maze rules (used by the tests)."""
    if not path:
        return False, "empty path"
    if tuple(path[0]) != maze.start:
        return False, "path does not begin at the start"
    has_key = False
    for i, (r, c) in enumerate(path):
        if maze.is_wall(r, c):
            return False, "path crosses a wall at (%d, %d)" % (r, c)
        if i:
            pr, pc = path[i - 1]
            if abs(pr - r) + abs(pc - c) != 1:
                return False, "path jumps between (%d, %d) and (%d, %d)" % (pr, pc, r, c)
        if (r, c) == maze.key:
            has_key = True
        if (r, c) == maze.exit and not has_key:
            return False, "path enters the exit without the keycard"
    if tuple(path[-1]) != maze.exit:
        return False, "path does not end at the exit"
    return True, "ok"
