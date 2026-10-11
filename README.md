# AI Escape Room Solver

A browser escape-room game where you solve three puzzle rooms yourself, or ask an in-game
AI assistant to solve them with classic search, constraint-solving and logic algorithms.
It is built with **Python 3 + Flask** (backend) and **HTML5 + CSS3 + vanilla JavaScript** (frontend).
No Node.js, no npm, no build step, no API key, no internet connection needed.

> The "AI" is rule-based: deterministic algorithms written in Python, with explanations generated from
> the real game state and the real solver output. No external AI service is used.

## The game

| Stage | Puzzle | Algorithm |
|---|---|---|
| Room 1 - Maze | 9x9 laser maze. Collect the keycard, then reach the locked exit. Laser grids cost 5, floor costs 1. | **A\***, **BFS**, **DFS**, **UCS** (you choose) |
| Room 2 - Safe code | Seven clues describe a 3-digit code (leading zeros count). | **Backtracking CSP with forward checking** |
| Room 3 - Switches | Three switches feed six rules. Light the exit lamp without a short circuit. | **Forward chaining** + **backward chaining** |
| Exit | Needs: maze done, keycard, safe open, access chip, power restored. | Server-side requirement check |

Every room has **AI solve** (runs the algorithm and shows its reasoning), **AI hint** (counts as a hint) and
**Apply AI solution** (the *server* recomputes the answer and applies it; the browser never sends a path or a
"solved" flag). In Room 1 you can also walk yourself with the arrow buttons or the keyboard arrow keys.

### Algorithms in short
* **BFS** finds the route with the fewest *moves*. It ignores tile costs, so it can walk through laser grids and pay more.
* **UCS** expands the cheapest-so-far state, so it finds the lowest *cost* route. **A\*** does the same using a heuristic
  (distance to the keycard, then to the exit), so it expands fewer states. **DFS** finds *a* route, not a good one.
* **Safe code**: each digit is a variable (0-9). Clues remove impossible digits, the search assigns D1, D2, D3 in turn,
  forward checking prunes later digits, dead ends make it back up, and it keeps going to prove the answer is unique.
  The code is *derived* from the clues; it is not stored anywhere.
* **Switches**: forward chaining fires every rule whose premises are known until nothing new appears; backward chaining
  starts at `exit_light_on` and shows which facts are needed. The solver tries all 8 switch settings.

## Requirements
* Python **3.9 or newer** (developed and tested on 3.12)
* Flask 3 (installed from `requirements.txt`)

## Windows setup
Open **Command Prompt** in the project folder (the one containing `run.bat`):

```bat
python -m venv venv
venv\Scripts\python -m pip install -r requirements.txt
run.bat
```

`run.bat` uses `venv` when it exists, checks that Python and Flask are available, starts the server and opens
**http://127.0.0.1:5000** in your browser. Stop it with `Ctrl+C`.

Other systems:

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m backend.app          # always run from the project folder
```

Optional environment variables: `PORT` (default 5000) and `HOST` (default 127.0.0.1).

## Running the tests
From the project folder:

```bat
venv\Scripts\python -m unittest discover -s tests -t . -v
```

The suite covers the app and static files, initial state, maze data and all four algorithms (legality, hazard costs,
keycard rule, unreachable goals), the safe solver (checked against brute force), the switch rules (all 8 settings),
room progression locks, inventory, the final exit, reset/replay and invalid requests.

## Project structure
```
AI_Escape_Room_Solver/
  backend/
    app.py            Flask routes (JSON API) and static file serving
    game_state.py     Single source of truth: rooms, inventory, objectives, timer, log
    maze_solver.py    Maze data + BFS / DFS / UCS / A*
    safe_solver.py    Safe-code CSP (backtracking + forward checking)
    switch_solver.py  Rule engine (forward/backward chaining) + brute-force solver
  frontend/           index.html, style.css, script.js (vanilla JS, no build)
  assets/             Local SVG artwork and icons
  tests/              unittest suites
  requirements.txt  README.md  run.bat  .gitignore
```

## How state works
The server keeps one in-memory game (single local player, nothing is saved to disk; restarting the server restarts the
game). The page loads `GET /api/state`, draws everything from it, and every action returns the new full state.
Moves = maze steps + code tries + switch flips + switch evaluations. Hints = AI hint presses. The timer runs on the
server and stops when you escape.

## API
All responses are JSON: `{"ok": true, ...}` or `{"ok": false, "error": "...", "state": {...}}` with an HTTP error status
(400 bad request, 403 locked/not allowed, 409 not possible right now, 404/405 unknown route, 500 unexpected).

| Method & path | Body | Purpose |
|---|---|---|
| `GET /api/state` | - | Full game state |
| `POST /api/reset` | - | Restart everything (inventory, rooms, puzzles, moves, hints, timer, log) |
| `POST /api/navigate` | `{"room": 1-4}` | Go to an unlocked room (403 if locked) |
| `POST /api/hint` | - | Hint for the current room (counts as a hint) |
| `POST /api/inspect` | `{"item": "keycard"\|"chip"}` | Inspect a collected item |
| `GET /api/maze` | - | Maze layout and player data |
| `POST /api/maze/algorithm` | `{"algorithm": "bfs"\|"dfs"\|"ucs"\|"astar"}` | Select the algorithm |
| `POST /api/maze/solve` | `{"algorithm"?}` | Search from the player's position; returns path, explored cells, cost, trace |
| `POST /api/maze/apply` | `{"algorithm"?}` | Server re-solves and walks the route (moves are counted) |
| `POST /api/maze/move` | `{"direction": "up"\|"down"\|"left"\|"right"}` | One step (409 for walls or the locked exit) |
| `POST /api/maze/complete` | - | Confirms completion; only succeeds at the exit holding the keycard |
| `GET /api/safe` | - | Marks the clue paper as read (Room 2 only) |
| `GET /api/safe/solve` | - | Runs the CSP solver; returns steps, domains, the unique code |
| `POST /api/safe/check` | `{"code": "042"}` | Validates a code; opens the safe and gives the chip when correct |
| `POST /api/safe/apply` | - | Server solves and submits the code |
| `GET /api/switches` | - | Switch config + live rule evaluation (Room 3) |
| `POST /api/switches/toggle` | `{"switch": "A"\|"B"\|"C"}` | Flip a switch |
| `POST /api/switches/check` | `{"switches": {"A":true,"B":true,"C":false}}` (optional) | Validate; restores power when valid |
| `GET /api/switches/solve` | - | Brute-force rule solver |
| `POST /api/switches/apply` | - | Server sets the solution and checks it |
| `GET /api/exit` | - | Exit requirements and which are met |
| `POST /api/exit/open` | - | Escape (403 with the unmet requirements if locked) |

## Troubleshooting
* **"Python was not found"** - install Python 3 and tick *Add python.exe to PATH*, then reopen the terminal.
* **"No module named flask"** - run `python -m pip install -r requirements.txt` (inside the venv).
* **"No module named backend"** - start from the project folder with `python -m backend.app` (or use `run.bat`).
* **Port 5000 already in use** - `set PORT=5001` before starting, then open http://127.0.0.1:5001.
* **Page says it cannot reach the server** - the server window was closed; start `run.bat` again.
* **Styles missing** - open the page through Flask (http://127.0.0.1:5000), not by double-clicking `index.html`.
