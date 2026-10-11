"""Room 2 - the safe code, solved as a Constraint Satisfaction Problem (CSP).

Variables   D1, D2, D3  - the three digits of the code
Domains     0..9 for every variable (leading zeros count)
Constraints seven clues (see ``CLUES``)

The solver is *backtracking search with forward checking*:
  1. Before searching, every digit that already breaks a clue is removed from its domain.
  2. The search assigns D1, then D2, then D3.  After each assignment, forward checking
     removes the values of the later variables that can no longer satisfy a clue.
  3. If a variable has no values left, that branch is a dead end and the search backs up.
  4. The search keeps going after the first answer, so it can prove the answer is unique.

The code that opens the safe is *derived* from the clues - it is not stored anywhere.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

CODE_LENGTH = 3
DIGITS = list(range(10))
VAR_NAMES = ["D1", "D2", "D3"]

# "match" clues: a test code and how many of its digits are in the code.
#   placed    = digits that are correct AND in the right position
#   misplaced = digits that are correct but in the wrong position
CLUES: List[dict] = [
    {"id": 1, "kind": "match", "guess": [6, 8, 2], "placed": 1, "misplaced": 0},
    {"id": 2, "kind": "match", "guess": [6, 1, 4], "placed": 0, "misplaced": 1},
    {"id": 3, "kind": "match", "guess": [2, 0, 6], "placed": 0, "misplaced": 2},
    {"id": 4, "kind": "match", "guess": [7, 3, 8], "placed": 0, "misplaced": 0},
    {"id": 5, "kind": "match", "guess": [7, 8, 0], "placed": 0, "misplaced": 1},
    {"id": 6, "kind": "greater", "left": 1, "right": 2},   # D2 > D3
    {"id": 7, "kind": "alldiff"},                           # all digits different
]

_COUNT_WORDS = {0: "No", 1: "One", 2: "Two", 3: "Three"}


class SafeError(ValueError):
    """Raised for malformed codes."""


# ----------------------------------------------------------------------
# Clue text
# ----------------------------------------------------------------------
def clue_text(clue: dict) -> str:
    if clue["kind"] == "greater":
        return "The middle digit is greater than the last digit."
    if clue["kind"] == "alldiff":
        return "All three digits are different."
    placed, misplaced = clue["placed"], clue["misplaced"]
    total = placed + misplaced
    if total == 0:
        return "No digit is correct."
    word = _COUNT_WORDS[total]
    plural = "digit is" if total == 1 else "digits are"
    if misplaced == 0:
        where = "in the right position" if total == 1 else "in the right positions"
        return "%s %s correct and %s." % (word, plural, where)
    if placed == 0:
        if total == 1:
            return "One digit is correct but in the wrong position."
        return "%s digits are correct but %s in the wrong positions." % (
            word, "both are" if total == 2 else "all are")
    return "%s %s correct: %d in the right position, %d in the wrong position." % (
        word, plural, placed, misplaced)


def public_clues() -> List[dict]:
    """Clues in a JSON-friendly form for the frontend."""
    out = []
    for clue in CLUES:
        item = {"id": clue["id"], "kind": clue["kind"], "text": clue_text(clue)}
        if clue["kind"] == "match":
            item["guess"] = list(clue["guess"])
        elif clue["kind"] == "greater":
            item["left"] = VAR_NAMES[clue["left"]]
            item["right"] = VAR_NAMES[clue["right"]]
        out.append(item)
    return out


# ----------------------------------------------------------------------
# Checking a complete code
# ----------------------------------------------------------------------
def parse_code(code) -> List[int]:
    if not isinstance(code, str):
        raise SafeError("The code must be sent as text, for example \"042\".")
    code = code.strip()
    if len(code) != CODE_LENGTH or not code.isascii() or not code.isdigit():
        raise SafeError("Enter exactly %d digits (0-9). Leading zeros count." % CODE_LENGTH)
    return [int(ch) for ch in code]


def _match_counts(guess: List[int], digits: List[int]) -> Tuple[int, int]:
    placed = sum(1 for g, d in zip(guess, digits) if g == d)
    present = sum(1 for g in guess if g in digits)
    return placed, present - placed


def broken_clues(digits: List[int]) -> List[int]:
    """Ids of the clues that a complete code breaks."""
    broken = []
    for clue in CLUES:
        if clue["kind"] == "match":
            placed, misplaced = _match_counts(clue["guess"], digits)
            ok = placed == clue["placed"] and misplaced == clue["misplaced"]
        elif clue["kind"] == "greater":
            ok = digits[clue["left"]] > digits[clue["right"]]
        else:
            ok = len(set(digits)) == len(digits)
        if not ok:
            broken.append(clue["id"])
    return broken


# ----------------------------------------------------------------------
# Partial reasoning (domains) - used for pruning and forward checking
# ----------------------------------------------------------------------
Domains = List[set]


def _violation(clue: dict, domains: Domains) -> Optional[str]:
    """Why the clue can no longer be satisfied given the domains, or None if it still can."""
    if clue["kind"] == "match":
        guess = clue["guess"]
        need_placed = clue["placed"]
        need_total = clue["placed"] + clue["misplaced"]
        label = "clue %d (%s)" % (clue["id"], "".join(str(g) for g in guess))
        placed_min = sum(1 for i, g in enumerate(guess) if domains[i] == {g})
        placed_max = sum(1 for i, g in enumerate(guess) if g in domains[i])
        total_min = sum(1 for g in guess if any(d == {g} for d in domains))
        total_max = sum(1 for g in guess if any(g in d for d in domains))
        if need_placed > placed_max:
            return "%s wants %d digit(s) in the right position, but at most %d can be" % (
                label, need_placed, placed_max)
        if need_placed < placed_min:
            return "%s wants %d digit(s) in the right position, but at least %d already are" % (
                label, need_placed, placed_min)
        if need_total > total_max:
            return "%s wants exactly %d digit(s) of its test code in the code, but at most %d can be" % (
                label, need_total, total_max)
        if need_total < total_min:
            return "%s wants exactly %d digit(s) of its test code in the code, but at least %d already are" % (
                label, need_total, total_min)
        return None
    if clue["kind"] == "greater":
        left, right = clue["left"], clue["right"]
        if any(a > b for a in domains[left] for b in domains[right]):
            return None
        return "clue %d needs %s > %s, but no remaining values allow it" % (
            clue["id"], VAR_NAMES[left], VAR_NAMES[right])
    # all different: two variables fixed to the same value
    fixed = [(i, next(iter(d))) for i, d in enumerate(domains) if len(d) == 1]
    for a in range(len(fixed)):
        for b in range(a + 1, len(fixed)):
            if fixed[a][1] == fixed[b][1]:
                return "clue %d needs all digits different, but %s and %s would both be %d" % (
                    clue["id"], VAR_NAMES[fixed[a][0]], VAR_NAMES[fixed[b][0]], fixed[a][1])
    return None


def _value_problem(var: int, value: int, domains: Domains) -> Optional[str]:
    trial = [set(d) for d in domains]
    trial[var] = {value}
    for clue in CLUES:
        reason = _violation(clue, trial)
        if reason:
            return reason
    return None


def _initial_pruning() -> Tuple[Domains, List[dict]]:
    domains: Domains = [set(DIGITS) for _ in range(CODE_LENGTH)]
    removals = []
    for var in range(CODE_LENGTH):
        for value in DIGITS:
            reason = _value_problem(var, value, domains)
            if reason:
                removals.append({"var": VAR_NAMES[var], "value": value, "reason": reason})
    for item in removals:
        domains[VAR_NAMES.index(item["var"])].discard(item["value"])
    return domains, removals


# ----------------------------------------------------------------------
# The search
# ----------------------------------------------------------------------
_MAX_STEPS = 80
_CACHE: Optional[dict] = None


def solve() -> dict:
    """Run the CSP search and return the solutions plus a replayable trace."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    domains, removals = _initial_pruning()
    steps: List[dict] = []
    stats = {"choices": 0, "removed": len(removals), "backtracks": 0, "solutions": 0}
    solutions: List[str] = []

    overflow = {"hit": False}

    def add(kind: str, text: str):
        if len(steps) < _MAX_STEPS:
            steps.append({"kind": kind, "text": text})
        else:
            overflow["hit"] = True

    def so_far(assigned: List[int]) -> str:
        return "".join(str(d) for d in assigned) + "?" * (CODE_LENGTH - len(assigned))

    def search(var: int, doms: Domains, assigned: List[int]):
        for value in sorted(doms[var]):
            stats["choices"] += 1
            now = assigned + [value]
            add("Try", "%s = %d (code so far: %s)" % (VAR_NAMES[var], value, so_far(now)))
            nxt = [set(d) for d in doms]
            nxt[var] = {value}
            if var == CODE_LENGTH - 1:
                broken = broken_clues(now)
                if broken:
                    stats["backtracks"] += 1
                    add("Dead end", "Code %s breaks clue %d" % (so_far(now), broken[0]))
                else:
                    stats["solutions"] += 1
                    code = so_far(now)
                    solutions.append(code)
                    add("Solved", "Code %s obeys every clue" % code)
                continue
            dead = False
            for later in range(var + 1, CODE_LENGTH):
                for cand in sorted(nxt[later]):
                    reason = _value_problem(later, cand, nxt)
                    if reason:
                        nxt[later].discard(cand)
                        stats["removed"] += 1
                        add("Remove", "%d from %s: %s" % (cand, VAR_NAMES[later], reason))
                if not nxt[later]:
                    stats["backtracks"] += 1
                    add("Dead end", "%s has no values left" % VAR_NAMES[later])
                    dead = True
                    break
            if not dead:
                search(var + 1, nxt, now)

    search(0, domains, [])

    unique = len(solutions) == 1
    if solutions:
        headline = ("Exactly one code obeys all the clues" if unique
                    else "%d codes obey all the clues" % len(solutions))
        detail = ("The search collected every solution, so the puzzle has only one answer." if unique
                  else "The search collected every solution; the puzzle is not unique.")
    else:
        headline, detail = "No code obeys all the clues", "The clues contradict each other."

    _CACHE = {
        "found": bool(solutions),
        "unique": unique,
        "solutions": solutions,
        "solution": solutions[0] if solutions else None,
        "initial_domains": [sorted(d) for d in domains],
        "initial_removals": removals,
        "steps": steps,
        "steps_truncated": overflow["hit"],
        "stats": stats,
        "headline": headline,
        "detail": detail,
        "title": "Backtracking",
        "tag": "with forward checking",
        "explanation": (
            "A constraint satisfaction problem: each digit is a variable from 0 to 9 and every clue "
            "removes digits that break it. The search tries what is left and backs up from dead ends."
        ),
    }
    return _CACHE


def correct_code() -> Optional[str]:
    """The unique code that obeys every clue (derived by the solver)."""
    result = solve()
    return result["solution"] if result["unique"] else None


def check_code(code) -> dict:
    """Validate a submitted code against the clues and the solver's answer."""
    digits = parse_code(code)
    broken = broken_clues(digits)
    text = "".join(str(d) for d in digits)
    return {"code": text, "broken": broken, "correct": not broken and text == correct_code()}


def describe_broken(code: str, broken: List[int]) -> str:
    if not broken:
        return "This code obeys every clue."
    if len(broken) == 1:
        return "This code breaks clue %d." % broken[0]
    head = ", ".join(str(b) for b in broken[:-1])
    return "This code breaks clues %s and %d." % (head, broken[-1])


def hint_for_level(level: int) -> str:
    """Progressive, deterministic hints computed from the solver's own reasoning."""
    result = solve()
    domains = result["initial_domains"]
    if level <= 0:
        zero = next((c for c in CLUES if c["kind"] == "match" and c["placed"] + c["misplaced"] == 0), None)
        if zero:
            digits = ", ".join(str(d) for d in zero["guess"])
            return "Clue %d rules out %s. None of those digits is in the code." % (zero["id"], digits)
    if level <= 1:
        remaining = " and ".join("%s: %s" % (VAR_NAMES[i], "/".join(str(d) for d in domains[i]))
                                 for i in range(CODE_LENGTH))
        return "After the impossible digits are removed, the digits still possible are %s." % remaining
    if level == 2 and result["solution"]:
        return "The first digit of the code is %s." % result["solution"][0]
    return "Press AI solve to see the full search and the code."
