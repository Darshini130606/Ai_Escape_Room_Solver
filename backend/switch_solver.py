"""Room 3 - the switch panel, solved with a small rule-based (logic) system.

Facts      has_keycard, safe_unlocked (from the earlier rooms) and switch_A_on / switch_B_on / switch_C_on
Rules      "if every premise is known, then the conclusion is known"
Goal       prove ``exit_light_on`` WITHOUT deriving the conflict ``short_circuit``

Forward chaining starts from the known facts and fires every rule whose premises are all true,
repeating until nothing new can be derived.  Backward chaining starts from the goal and works out
which facts are needed to prove it.  The solver tries all 8 switch settings.
"""
from __future__ import annotations

from itertools import product
from typing import Dict, List, Optional

SWITCHES = ["A", "B", "C"]
GOAL = "exit_light_on"
CONFLICT = "short_circuit"

RULES: List[dict] = [
    {"id": "R1", "premises": ["has_keycard", "switch_A_on"], "conclusion": "power_online", "tag": ""},
    {"id": "R2", "premises": ["power_online", "switch_B_on"], "conclusion": "door_A_open", "tag": ""},
    {"id": "R3", "premises": ["switch_B_on", "switch_C_on"], "conclusion": "short_circuit", "tag": "conflict"},
    {"id": "R4", "premises": ["door_A_open", "safe_unlocked"], "conclusion": "control_panel_active", "tag": ""},
    {"id": "R5", "premises": ["control_panel_active"], "conclusion": "exit_light_on", "tag": ""},
    {"id": "R6", "premises": ["power_online", "switch_C_on"], "conclusion": "backup_lamp_on", "tag": "decoy"},
]
_RULE_FOR = {r["conclusion"]: r for r in RULES}

KEYCARD_NOTE = "Switch C is wired against B."

INFO = {
    "title": "Forward chaining",
    "tag": "if premises, then conclusion",
    "text": ("Start from the known facts and fire every rule whose premises are all true. "
             "Repeat until nothing new can be derived."),
}


class SwitchError(ValueError):
    """Raised for malformed switch configurations."""


def validate_config(config) -> Dict[str, bool]:
    if not isinstance(config, dict):
        raise SwitchError("Send the switches as an object, for example {\"A\": true, \"B\": false, \"C\": true}.")
    unknown = [k for k in config if k not in SWITCHES]
    missing = [k for k in SWITCHES if k not in config]
    if unknown or missing:
        raise SwitchError("The switch panel has exactly the switches A, B and C.")
    if any(not isinstance(v, bool) for v in config.values()):
        raise SwitchError("Every switch must be true (on) or false (off).")
    return {k: config[k] for k in SWITCHES}


def base_facts(config: Dict[str, bool], has_keycard: bool, safe_unlocked: bool) -> List[str]:
    facts = []
    if has_keycard:
        facts.append("has_keycard")
    if safe_unlocked:
        facts.append("safe_unlocked")
    facts += ["switch_%s_on" % name for name in SWITCHES if config.get(name)]
    return facts


def forward_chain(facts: List[str]) -> dict:
    known = list(facts)
    fired = []
    changed = True
    while changed:
        changed = False
        for rule in RULES:
            if rule["conclusion"] in known:
                continue
            if all(p in known for p in rule["premises"]):
                known.append(rule["conclusion"])
                fired.append({"rule": rule["id"], "premises": list(rule["premises"]),
                              "derived": rule["conclusion"], "tag": rule["tag"]})
                changed = True
    return {"known": known, "fired": fired}


def backward_chain(goal: str, facts: List[str]) -> dict:
    """Prove ``goal`` from the base facts, returning an indented proof tree."""
    lines: List[dict] = []

    def walk(fact: str, prefix: str, connector: str, child_prefix: str) -> bool:
        if fact in facts:
            lines.append({"prefix": prefix + connector, "fact": fact, "via": None, "status": "known"})
            return True
        rule = _RULE_FOR.get(fact)
        if rule is None:
            lines.append({"prefix": prefix + connector, "fact": fact, "via": None, "status": "missing"})
            return False
        index = len(lines)
        lines.append({"prefix": prefix + connector, "fact": fact, "via": rule["id"], "status": "proved"})
        ok = True
        count = len(rule["premises"])
        for i, premise in enumerate(rule["premises"]):
            last = i == count - 1
            sub_ok = walk(premise, child_prefix, "└ " if last else "├ ",
                          child_prefix + ("  " if last else "│ "))
            ok = ok and sub_ok
        if not ok:
            lines[index]["status"] = "unproved"
        return ok

    proved = walk(goal, "", "", "")
    return {"goal": goal, "proved": proved, "lines": lines}


def _lamps(known: List[str]) -> List[dict]:
    def lamp(key, label, fact, on_text, off_text):
        on = fact in known
        return {"key": key, "label": label, "on": on, "text": on_text if on else off_text}

    exit_on = GOAL in known
    short = CONFLICT in known
    exit_lamp = {"key": "exit_light", "label": "Exit light", "on": exit_on and not short,
                 "text": "Blocked" if (exit_on and short) else ("Lit" if exit_on else "Off")}
    return [
        lamp("power", "Power", "power_online", "Online", "Offline"),
        lamp("door", "Door A", "door_A_open", "Open", "Closed"),
        lamp("panel", "Control panel", "control_panel_active", "Active", "Inactive"),
        exit_lamp,
        lamp("backup", "Backup lamp", "backup_lamp_on", "On", "Off"),
        {"key": "short", "label": "Short circuit", "on": short, "alarm": True,
         "text": "Alarm" if short else "Clear"},
    ]


def evaluate(config: Dict[str, bool], has_keycard: bool, safe_unlocked: bool) -> dict:
    """Run both reasoning directions on a switch setting."""
    config = validate_config(config)
    facts = base_facts(config, has_keycard, safe_unlocked)
    forward = forward_chain(facts)
    known = forward["known"]
    conflicts = [f["derived"] for f in forward["fired"] if f["tag"] == "conflict"]
    exit_lit = GOAL in known
    success = exit_lit and not conflicts

    if success:
        verdict = {"level": "success", "title": "Power restored",
                   "text": "The exit light is on and no short circuit was derived."}
    elif exit_lit:
        conflict_rule = next(r for r in RULES if r["conclusion"] == conflicts[0])
        switches = [p.replace("switch_", "").replace("_on", "") for p in conflict_rule["premises"]
                    if p.startswith("switch_")]
        which = (" and ".join(switches) + " are both on.") if len(switches) > 1 else ""
        verdict = {"level": "error", "title": "Exit blocked",
                   "text": "The exit light can be proved, but %s was derived too. Switches %s" % (
                       conflicts[0], which)}
    else:
        proof = backward_chain(GOAL, facts)
        missing = [l["fact"] for l in proof["lines"] if l["status"] == "missing"]
        verdict = {"level": "error", "title": "Exit light is off",
                   "text": "exit_light_on cannot be derived. Missing: %s." % ", ".join(missing or ["unknown"])}

    return {
        "config": dict(config),
        "facts": facts,
        "known": known,
        "fired": forward["fired"],
        "conflicts": conflicts,
        "lamps": _lamps(known),
        "proof": backward_chain(GOAL, facts),
        "success": success,
        "verdict": verdict,
        "stats": {
            "rules_fired": len(forward["fired"]),
            "facts_derived": len(forward["fired"]),
            "conflicts": len(conflicts),
            "switches_on": sum(1 for v in config.values() if v),
        },
    }


def all_valid_configs(has_keycard: bool = True, safe_unlocked: bool = True) -> List[Dict[str, bool]]:
    """Brute force the 8 switch settings and keep the ones that restore power."""
    valid = []
    for values in product([False, True], repeat=len(SWITCHES)):
        config = dict(zip(SWITCHES, values))
        if evaluate(config, has_keycard, safe_unlocked)["success"]:
            valid.append(config)
    return valid


def solve(has_keycard: bool = True, safe_unlocked: bool = True) -> dict:
    valid = all_valid_configs(has_keycard, safe_unlocked)
    solution = valid[0] if valid else None
    result = {
        "found": bool(valid),
        "unique": len(valid) == 1,
        "solution": solution,
        "checked": 2 ** len(SWITCHES),
        "valid_count": len(valid),
        "title": INFO["title"],
        "tag": INFO["tag"],
        "explanation": INFO["text"],
    }
    if solution:
        result["evaluation"] = evaluate(solution, has_keycard, safe_unlocked)
        on = [n for n in SWITCHES if solution[n]]
        off = [n for n in SWITCHES if not solution[n]]
        result["headline"] = "Switches %s on, %s off" % (", ".join(on) or "none", ", ".join(off) or "none")
        result["detail"] = ("The solver tried all %d settings with forward chaining. %d setting(s) light the "
                            "exit without a short circuit." % (result["checked"], len(valid)))
    else:
        result["headline"] = "No setting works"
        result["detail"] = "None of the settings lights the exit light without a short circuit."
    return result


def hint(config: Dict[str, bool], has_keycard: bool, safe_unlocked: bool) -> str:
    """A deterministic nudge computed from the current evaluation."""
    ev = evaluate(config, has_keycard, safe_unlocked)
    if ev["success"]:
        return "This setting already works. Press Evaluate switches to confirm it."
    if ev["conflicts"]:
        rule = next(r for r in RULES if r["conclusion"] == ev["conflicts"][0])
        switches = [p.replace("switch_", "").replace("_on", "") for p in rule["premises"] if p.startswith("switch_")]
        # the keycard note says which switch is "wired against" which
        off_switch = switches[-1]
        return "Turn switch %s off. Rule %s derives %s only when %s are both on." % (
            off_switch, rule["id"], rule["conclusion"], " and ".join(switches))
    missing = [l["fact"] for l in ev["proof"]["lines"] if l["status"] == "missing" and l["fact"].startswith("switch_")]
    if missing:
        name = missing[0].replace("switch_", "").replace("_on", "")
        return "Turn switch %s on. The proof of exit_light_on needs %s." % (name, missing[0])
    return "Evaluate the switches and read which rules fire."
