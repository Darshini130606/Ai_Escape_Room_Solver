/* AI Escape Room Solver - frontend (vanilla JavaScript).
 *
 * The browser never decides whether a puzzle is solved. It sends requests to the Flask API,
 * receives the full game state back, and draws it. All text is inserted with textContent,
 * never as HTML.
 */
(function () {
  "use strict";

  // ------------------------------------------------------------------
  // Tiny DOM helpers
  // ------------------------------------------------------------------
  const SVG_NS = "http://www.w3.org/2000/svg";
  const $ = (sel) => document.querySelector(sel);

  function el(tag, attrs, ...kids) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v === false || v === null || v === undefined) continue;
        if (k === "class") node.className = v;
        else if (k === "text") node.textContent = v;
        else node.setAttribute(k, v === true ? "" : String(v));
      }
    }
    for (const kid of kids.flat()) {
      if (kid === null || kid === undefined || kid === false) continue;
      node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return node;
  }

  function svg(tag, attrs, ...kids) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, String(v));
    for (const kid of kids.flat()) if (kid) node.append(kid);
    return node;
  }

  function fmtTime(seconds) {
    const s = Math.max(0, Math.floor(seconds));
    return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
  }

  // ------------------------------------------------------------------
  // State
  // ------------------------------------------------------------------
  let state = null;
  const ui = {
    busy: false,
    digits: ["", "", ""],
    clueFetching: false,
    restartArmed: false,
    restartTimer: null,
    winDismissed: false,
    timerBase: { elapsed: 0, at: 0, running: true },
    logCount: 0,
    pendingFocus: null,
  };

  // ------------------------------------------------------------------
  // API
  // ------------------------------------------------------------------
  async function api(path, method, body) {
    const options = { method: method || "GET", headers: {} };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    let res;
    try {
      res = await fetch(path, options);
    } catch (networkError) {
      showNetError("Cannot reach the game server. Check that it is still running, then try again.");
      const err = new Error("network");
      err.network = true;
      throw err;
    }
    hideNetError();
    let data = null;
    try {
      data = await res.json();
    } catch (parseError) {
      data = null;
    }
    if (!res.ok || !data || data.ok === false) {
      const err = new Error((data && data.error) || "The server answered with an error (" + res.status + ").");
      err.state = data && data.state;
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function showNetError(text) {
    $("#net-error-text").textContent = text;
    $("#net-error").hidden = false;
  }
  function hideNetError() {
    $("#net-error").hidden = true;
  }

  /** Run one request. Only one request at a time, so clicks cannot race each other. */
  async function act(call) {
    if (ui.busy) return null;
    ui.busy = true;
    const focused = document.activeElement;
    if (focused && focused.dataset && focused.dataset.key) ui.pendingFocus = focused.dataset.key;
    $("#main").setAttribute("aria-busy", "true");
    render();
    try {
      const data = await call();
      if (data && data.state) applyState(data.state);
      return data;
    } catch (err) {
      if (err.state) applyState(err.state);
      else if (!err.network && state) state.output = { level: "error", text: err.message };
      return null;
    } finally {
      ui.busy = false;
      $("#main").setAttribute("aria-busy", "false");
      render();
      ui.pendingFocus = null;
    }
  }

  function applyState(next) {
    state = next;
    ui.timerBase = { elapsed: next.stats.elapsed, at: performance.now(), running: next.stats.running };
    // After a successful safe opening, show the accepted code in the boxes.
    if (next.safe && next.safe.unlocked && next.safe.tries.length) {
      const last = next.safe.tries[next.safe.tries.length - 1].code;
      ui.digits = last.split("");
    }
  }

  function localMessage(level, text) {
    if (!state) return;
    state.output = { level: level, text: text };
    renderDash();
  }

  // ------------------------------------------------------------------
  // Rendering: header, stepper
  // ------------------------------------------------------------------
  function renderHud() {
    $("#hud-moves").textContent = state.stats.moves;
    $("#hud-hints").textContent = state.stats.hints;
    $("#hud-mission").textContent = state.mission.status;
    updateTimer();
    const pill = $("#room-pill");
    pill.classList.toggle("pill-done", state.mission.complete);
    $("#room-pill-text").textContent = state.mission.complete
      ? "Escaped"
      : state.current_room === 4 ? "At the exit" : "Playing in Room " + state.current_room;
    $("#restart-btn").textContent = ui.restartArmed ? "Click again to restart" : "Restart";
    $("#restart-btn").classList.toggle("btn-danger", ui.restartArmed);
    $("#restart-btn").disabled = ui.busy;
  }

  function updateTimer() {
    if (!state) return;
    const b = ui.timerBase;
    const extra = b.running ? (performance.now() - b.at) / 1000 : 0;
    $("#hud-time").textContent = fmtTime(b.elapsed + extra);
  }

  function renderStepper() {
    const nodes = [];
    state.rooms.forEach((room, i) => {
      const done = room.status === "complete";
      const badge = el("span", { class: "step-badge", "aria-hidden": "true" }, done ? "\u2713" : room.status === "locked" ? "\u{1F512}" : String(room.id));
      const btn = el("button", {
        type: "button", class: "step is-" + room.status, "data-action": "goto", "data-room": room.id,
        "data-key": "goto-" + room.id, "aria-current": room.status === "active" ? "step" : false,
        "aria-label": "Room " + room.id + ", " + room.name + ", " + room.label,
        disabled: ui.busy,
      }, badge, el("span", null, el("span", { class: "step-name", text: room.name }), el("span", { class: "step-label", text: room.label })));
      nodes.push(btn);
      if (i < state.rooms.length - 1) nodes.push(el("span", { class: "step-line" + (done ? " is-done" : ""), "aria-hidden": "true" }));
    });
    $("#stepper").replaceChildren(...nodes);
  }

  // ------------------------------------------------------------------
  // Small component helpers
  // ------------------------------------------------------------------
  function button(label, action, opts) {
    opts = opts || {};
    const attrs = {
      type: "button", class: opts.cls || "btn", "data-action": action,
      "data-key": action + (opts.key || ""), disabled: ui.busy || !!opts.disabled,
    };
    if (opts.data) for (const [k, v] of Object.entries(opts.data)) attrs["data-" + k] = v;
    if (opts.label) attrs["aria-label"] = opts.label;
    if (opts.pressed !== undefined) attrs["aria-pressed"] = String(opts.pressed);
    return el("button", attrs, label);
  }

  function statGrid(pairs) {
    return el("div", { class: "stats" }, pairs.map((p) => el("div", { class: "stat" }, el("b", { text: String(p[0]) }), el("span", { text: p[1] }))));
  }

  function resultBox(level, title, lines, code) {
    return el("div", { class: "result " + level },
      el("h4", null, code ? el("span", { class: "result-code", text: code }) : null,
        el("span", { "aria-hidden": "true" }, level === "success" ? "\u2714" : level === "error" ? "\u26A0" : "\u2139"), title),
      lines.map((t) => el("p", { text: t })));
  }

  function algoHeader(info) {
    return [
      el("h3", { class: "algo-title" }, info.title, el("span", { class: "tag", text: info.tag })),
      el("p", { class: "algo-text", text: info.text }),
    ];
  }

  function agentBox() {
    const a = state.agent;
    const rows = [
      ["Room", a.room_name], ["Status", a.status], ["Active solver", a.algorithm || "none here"],
      ["Inventory", a.inventory.join(", ")], ["Best next action", a.next_action], ["Last solver result", a.last_result],
    ];
    const dl = el("dl", { class: "agent-box" });
    rows.forEach((r) => dl.append(el("dt", { text: r[0] }), el("dd", { text: r[1] })));
    return dl;
  }

  // ------------------------------------------------------------------
  // Rendering: left column (room scene)
  // ------------------------------------------------------------------
  function renderRoom() {
    const room = state.rooms[state.current_room - 1];
    const head = [el("h2", { text: room.title }), el("p", { class: "lead", text: room.blurb })];
    let body;
    if (state.current_room === 1) body = roomMaze();
    else if (state.current_room === 2) body = roomSafe();
    else if (state.current_room === 3) body = roomSwitches();
    else body = roomExit();
    $("#room-panel").replaceChildren(...head, ...body);
  }

  // ---- Room 1 -------------------------------------------------------
  function freshRoute() {
    const r = state.ai["1"];
    if (!r) return null;
    const same = r.start[0] === state.maze.pos[0] && r.start[1] === state.maze.pos[1] && r.had_key === state.maze.has_key;
    return same ? r : null;
  }

  function iconKey() {
    return svg("svg", { viewBox: "0 0 32 32", "aria-hidden": "true" },
      svg("circle", { cx: 10, cy: 16, r: 5.5, fill: "none", stroke: "#ffc94a", "stroke-width": 3 }),
      svg("path", { d: "M15.5 16H29M24 16v5M28 16v4", fill: "none", stroke: "#ffc94a", "stroke-width": 3, "stroke-linecap": "round" }));
  }
  function iconLock(open) {
    return svg("svg", { viewBox: "0 0 32 32", "aria-hidden": "true" },
      svg("rect", { x: 7, y: 14, width: 18, height: 13, rx: 2.5, fill: "none", stroke: "#e4d4ff", "stroke-width": 2.6 }),
      svg("path", { d: open ? "M11 14V9a5 5 0 0 1 9.5-2" : "M11 14V10a5 5 0 0 1 10 0v4", fill: "none", stroke: "#e4d4ff", "stroke-width": 2.6, "stroke-linecap": "round" }));
  }

  function mazeBoard() {
    const m = state.maze;
    const route = freshRoute();
    const explored = new Set();
    if (route) route.explored.forEach((c) => explored.add(c[0] + "," + c[1]));
    const trail = new Set(m.trail.map((c) => c[0] + "," + c[1]));

    const grid = el("div", {
      class: "grid", role: "img",
      style: "grid-template-columns: repeat(" + m.cols + ", 1fr);",
      "aria-label": "Maze, " + m.rows + " by " + m.cols + " tiles. You are at row " + m.pos[0] + ", column " + m.pos[1] +
        ". The keycard is at row " + m.key[0] + ", column " + m.key[1] + ". The locked exit is at row " + m.exit[0] + ", column " + m.exit[1] + ".",
    });
    m.layout.forEach((row, r) => {
      [...row].forEach((ch, c) => {
        const k = r + "," + c;
        const wall = ch === "#";
        const cls = ["cell"];
        if (wall) cls.push("wall");
        else if (ch === "H") cls.push("hazard");
        if (ch === "E") cls.push("exit");
        if (!wall && explored.has(k)) cls.push("explored");
        if (!wall && trail.has(k) && !(r === m.pos[0] && c === m.pos[1])) cls.push("trail");
        const cell = el("div", { class: cls.join(" ") });
        if (ch === "K" && !m.has_key) cell.append(iconKey());
        if (ch === "E") cell.append(iconLock(m.has_key));
        grid.append(cell);
      });
    });

    if (route && route.found && route.path.length > 1) {
      const toPoints = (cells) => cells.map((p) => (p[1] + 0.5) + "," + (p[0] + 0.5)).join(" ");
      const split = route.key_index;
      const first = split === null ? [] : route.path.slice(0, split + 1);
      const second = split === null ? route.path : route.path.slice(split);
      const overlay = svg("svg", { class: "route", viewBox: "0 0 " + m.cols + " " + m.rows, preserveAspectRatio: "none", "aria-hidden": "true" });
      const line = (cells, color) => {
        if (cells.length < 2) return;
        const common = { points: toPoints(cells), fill: "none", "stroke-linecap": "round", "stroke-linejoin": "round", "vector-effect": "non-scaling-stroke" };
        overlay.append(svg("polyline", Object.assign({}, common, { stroke: color, "stroke-opacity": 0.28, "stroke-width": 11 })));
        overlay.append(svg("polyline", Object.assign({}, common, { stroke: color, "stroke-width": 4 })));
      };
      line(second, "#c4a8ff");
      line(first, "#2de2f5");
      grid.append(overlay);
    }

    const player = el("div", {
      class: "player",
      style: "--cols:" + m.cols + "; left:" + ((m.pos[1] + 0.5) / m.cols * 100) + "%; top:" + ((m.pos[0] + 0.5) / m.rows * 100) + "%;",
      "aria-hidden": "true",
    });
    grid.append(player);
    return el("div", { class: "board" }, grid);
  }

  function legendItem(color, text, extra) {
    return el("span", null, el("i", { style: "background:" + color + (extra || "") }), text);
  }

  function roomMaze() {
    const m = state.maze;
    const done = m.complete;
    const seg = el("div", { class: "seg", role: "group", "aria-label": "Search algorithm" },
      m.algorithms.map((a) => button(a.label, "algo", { cls: "", data: { algo: a.id }, key: a.id, pressed: m.algorithm === a.id, label: a.title })));
    const controls = el("div", { class: "maze-controls" },
      seg,
      button("AI solve", "maze-solve", { cls: "btn btn-primary", disabled: done }),
      button("AI hint", "hint", { cls: "btn btn-outline-blue", disabled: done }),
      button("Apply AI solution", "maze-apply", { cls: "btn btn-outline-lilac", disabled: done }));
    const legend = el("div", { class: "legend" },
      legendItem("repeating-linear-gradient(135deg,#d63a6e 0 4px,#5a1030 4px 8px)", "Laser grid, cost " + m.hazard_cost),
      legendItem("#ffc94a", "Keycard"), legendItem("#3b2a7a", "Locked exit", "; border:2px solid #c4a8ff"),
      legendItem("#26396f", "Looked at by the AI"), legendItem("#2de2f5", "Route to keycard"), legendItem("#c4a8ff", "Route to exit"),
      legendItem("#6ea0ff", "You"));
    const out = [mazeBoard(), controls, legend];
    if (done) out.push(el("p", { class: "lead", text: "Room 1 is complete. Use the room map to continue." }));
    return out;
  }

  // ---- Room 2 -------------------------------------------------------
  function dialSvg() {
    const ticks = [];
    for (let i = 0; i < 12; i++) {
      const a = (i / 12) * Math.PI * 2;
      ticks.push(svg("line", { x1: 60 + Math.sin(a) * 50, y1: 60 - Math.cos(a) * 50, x2: 60 + Math.sin(a) * 56, y2: 60 - Math.cos(a) * 56, stroke: "#2de2f5", "stroke-width": 2 }));
    }
    return svg("svg", { class: "safe-dial", viewBox: "0 0 120 120", "aria-hidden": "true" },
      svg("circle", { cx: 60, cy: 60, r: 46, fill: "#050a1a", stroke: "#2de2f5", "stroke-width": 3 }), ticks,
      svg("line", { x1: 60, y1: 60, x2: 60, y2: 24, stroke: "#2de2f5", "stroke-width": 4, "stroke-linecap": "round" }),
      svg("circle", { cx: 60, cy: 60, r: 6, fill: "#2de2f5" }));
  }

  function roomSafe() {
    const s = state.safe;
    const lastTry = s.tries.length ? s.tries[s.tries.length - 1] : null;
    const digitInputs = [0, 1, 2].map((i) => el("input", {
      class: "digit", type: "text", inputmode: "numeric", maxlength: 1, autocomplete: "off", pattern: "[0-9]",
      value: ui.digits[i] || "", "data-key": "digit-" + i, "data-index": i,
      "aria-label": "Safe code digit " + (i + 1), disabled: s.unlocked || ui.busy,
    }));
    digitInputs.forEach((n, i) => { n.value = ui.digits[i] || ""; });

    let msgClass = "safe-msg", msgText = "Type three digits and press Try code.";
    if (s.unlocked) { msgClass += " ok"; msgText = "The safe is open. The access chip is in your inventory."; }
    else if (lastTry) { msgClass += " err"; msgText = lastTry.message + " (last try " + lastTry.code + ")"; }

    const box = el("div", { class: "safe" }, dialSvg(),
      el("div", { class: "safe-main" }, el("div", { class: "digits", role: "group", "aria-label": "Safe code" }, digitInputs), el("p", { class: msgClass, text: msgText })));

    const broken = lastTry ? new Set(lastTry.broken) : new Set();
    const clueItems = s.clues.map((c) => {
      const item = el("li", { class: "clue" + (broken.has(c.id) ? " is-broken" : "") });
      item.append(el("span", { class: "clue-no", text: String(c.id), "aria-label": "Clue " + c.id }));
      if (c.kind === "match") c.guess.forEach((d) => item.append(el("span", { class: "chip-digit", text: String(d) })));
      else if (c.kind === "greater") item.append(el("span", { class: "chip-digit chip-var", text: c.left }), el("span", { class: "chip-digit", text: ">" }), el("span", { class: "chip-digit chip-var", text: c.right }));
      else item.append(el("span", { class: "chip-digit chip-var", text: "all different" }));
      item.append(el("span", { text: c.text }));
      if (broken.has(c.id) && lastTry) item.append(el("span", { class: "broken-note", text: "broken by " + lastTry.code }));
      return item;
    });

    const actions = el("div", { class: "actions" },
      button("Try code", "safe-try", { cls: "btn btn-outline-blue", disabled: s.unlocked }),
      button("AI hint", "hint", { cls: "btn", disabled: s.unlocked }),
      button("AI solve", "safe-solve", { cls: "btn btn-primary", disabled: s.unlocked }),
      button("Apply AI solution", "safe-apply", { cls: "btn btn-outline-lilac", disabled: s.unlocked }));
    return [box, el("ol", { class: "clue-list", "aria-label": "Clues" }, clueItems), actions];
  }

  // ---- Room 3 -------------------------------------------------------
  function roomSwitches() {
    const sw = state.switches;
    if (!sw.available) return [el("p", { class: "empty", text: "This room is locked." })];
    const locked = sw.power_restored;
    const switches = ["A", "B", "C"].map((name) => {
      const on = sw.config[name];
      return el("button", {
        type: "button", class: "switch " + (on ? "on" : "off"), "data-action": "sw-toggle", "data-name": name,
        "data-key": "sw-" + name, role: "switch", "aria-checked": String(on), "aria-label": "Switch " + name, disabled: ui.busy || locked,
      }, el("span", { class: "switch-name", text: "Switch " + name }),
        el("span", { class: "switch-track", "aria-hidden": "true" }, el("span", { class: "switch-knob" })),
        el("span", { class: "switch-state", text: on ? "On" : "Off" }));
    });
    const lamps = el("div", { class: "lamps" }, sw.evaluation.lamps.map((l) =>
      el("div", { class: "lamp" + (l.on ? " on" : "") + (l.alarm ? " alarm" : "") + (l.text === "Blocked" ? " blocked" : "") },
        el("span", { class: "lamp-dot", "aria-hidden": "true" }),
        el("span", null, el("span", { class: "lamp-label", text: l.label }), el("span", { class: "lamp-text", text: l.text })))));
    const box = el("div", { class: "panel-box" }, el("div", { class: "switch-row" }, switches), lamps);
    const note = el("p", { class: "note" }, "Keycard note: ", el("b", { text: sw.note }));
    const actions = el("div", { class: "actions" },
      button("Evaluate switches", "sw-check", { cls: "btn btn-outline-blue", disabled: locked }),
      button("AI hint", "hint", { cls: "btn", disabled: locked }),
      button("AI solve", "sw-solve", { cls: "btn btn-primary", disabled: locked }),
      button("Apply AI solution", "sw-apply", { cls: "btn btn-outline-lilac", disabled: locked }));
    return [box, note, actions];
  }

  // ---- Final exit ---------------------------------------------------
  function roomExit() {
    const ex = state.exit;
    const list = el("ul", { class: "req-list", "aria-label": "Exit requirements" }, ex.requirements.map((r) =>
      el("li", null, el("span", { class: "mark " + (r.met ? "yes" : "miss"), "aria-hidden": "true", text: r.met ? "\u2713" : "\u2715" }),
        el("span", { text: r.label + (r.met ? "" : " (missing)") }))));
    const scene = el("div", { class: "exit-scene" + (ex.all_met ? " is-ready" : "") },
      el("img", { src: "/assets/door.svg", alt: ex.all_met ? "The exit door, ready to open" : "The exit door, locked" }), list);
    const actions = el("div", { class: "actions" },
      button("Open exit door", "exit-open", { cls: "btn btn-primary", disabled: ex.complete || !ex.all_met }),
      button("AI hint", "hint", { cls: "btn", disabled: ex.complete }));
    return [scene, actions];
  }

  // ------------------------------------------------------------------
  // Rendering: middle column (AI reasoning)
  // ------------------------------------------------------------------
  function renderAI() {
    const out = [
      el("h2", { text: "AI reasoning" }),
      el("p", { class: "lead", text: "Computed by the Python backend, not in the browser. The assistant is rule-based; no external AI service is used." }),
      agentBox(),
    ];
    if (state.current_room === 1) out.push(...aiMaze());
    else if (state.current_room === 2) out.push(...aiSafe());
    else if (state.current_room === 3) out.push(...aiSwitches());
    else out.push(el("h3", { class: "algo-title" }, "Final check"),
      el("p", { class: "algo-text", text: "The exit door verifies every requirement on the server. Nothing the browser sends can open it early." }));
    $("#ai-panel").replaceChildren(...out);
  }

  function aiMaze() {
    const m = state.maze;
    const info = m.algorithms.find((a) => a.id === m.algorithm);
    const out = algoHeader(info);
    const route = freshRoute();
    if (!route) {
      out.push(el("p", { class: "empty", text: state.ai["1"]
        ? "You moved since the last AI solve. Press AI solve again to search from where you stand."
        : "Press AI solve to run " + info.label + " from your current position, or move yourself with the arrows." }));
      return out;
    }
    out.push(statGrid([[route.moves, "moves"], [route.cost, "total cost"], [route.expanded, "states expanded"], [route.hazards, "hazards crossed"]]));
    if (route.trace.length) {
      const cols = route.trace_columns;
      const table = el("table", { class: "data" });
      const head = el("tr");
      cols.forEach((c) => head.append(el("th", { class: ["g", "h", "f"].includes(c) ? "num" : "", text: c === "state" ? "State (row, col)" : c === "key" ? "Key" : c })));
      table.append(el("thead", null, head));
      const tbody = el("tbody");
      route.trace.forEach((t) => {
        const tr = el("tr");
        cols.forEach((c) => {
          if (c === "state") tr.append(el("td", { text: "(" + t.state[0] + ", " + t.state[1] + ")" }));
          else if (c === "key") tr.append(el("td", { text: t.key ? "key" : "no key" }));
          else tr.append(el("td", { class: "num" + (c === "f" ? " hl" : ""), text: String(t[c]) }));
        });
        tbody.append(tr);
      });
      table.append(tbody);
      out.push(el("h3", { text: "First expansions" }), table);
    }
    out.push(resultBox(route.level, route.headline, route.messages));
    return out;
  }

  function aiSafe() {
    const info = state.safe.info;
    const out = algoHeader(info);
    const r = state.ai["2"];
    if (!r) {
      out.push(el("p", { class: "empty", text: "Press AI solve to run the constraint solver and see every step it takes." }));
      return out;
    }
    out.push(statGrid([[r.stats.choices, "choices tried"], [r.stats.removed, "values removed"], [r.stats.backtracks, "backtracks"], [r.stats.solutions, "solution(s) found"]]));
    const removed = (i, d) => !r.initial_domains[i].includes(d);
    out.push(el("h3", { text: "What each digit can still be" }));
    ["D1", "D2", "D3"].forEach((name, i) => {
      const row = el("div", { class: "domain", role: "group", "aria-label": name + " possible digits" }, el("span", { class: "vn", text: name }));
      for (let d = 0; d <= 9; d++) row.append(el("span", { class: "dv" + (removed(i, d) ? " gone" : ""), text: String(d), "aria-label": d + (removed(i, d) ? " removed" : " possible") }));
      out.push(row);
    });
    out.push(el("p", { class: "sub", text: "Crossed-out digits were removed by the clues before the search started." }));
    out.push(el("h3", { text: "Search steps" }));
    const list = el("ol", { class: "steps" });
    r.steps.forEach((s) => list.append(el("li", null, el("span", { class: "kind " + s.kind.split(" ")[0], text: s.kind }), el("span", { text: s.text }))));
    out.push(list);
    out.push(resultBox(r.found ? "success" : "error", r.headline, [r.detail], r.unique ? r.solution : null));
    return out;
  }

  function aiSwitches() {
    const sw = state.switches;
    const info = sw.info;
    const out = algoHeader(info);
    if (!sw.available) return out;
    const ev = sw.evaluation;
    out.push(statGrid([[ev.stats.rules_fired, "rules fired"], [ev.stats.facts_derived, "facts derived"], [ev.stats.conflicts, "conflict found"], [ev.stats.switches_on, "switches on"]]));
    out.push(el("h3", { text: "Rules fired, in order" }));
    if (ev.fired.length) {
      const table = el("table", { class: "data" }, el("thead", null, el("tr", null, el("th", { text: "Rule" }), el("th", { text: "Premises" }), el("th", { text: "Derived" }))));
      const body = el("tbody");
      ev.fired.forEach((f) => {
        const tag = f.tag === "conflict" ? " (conflict)" : f.tag === "decoy" ? " (decoy)" : "";
        body.append(el("tr", null, el("td", { class: "rule-id", text: f.rule }), el("td", { text: f.premises.join(", ") }),
          el("td", { class: f.tag === "conflict" ? "bad" : "", text: f.derived + tag })));
      });
      table.append(body);
      out.push(table);
    } else {
      out.push(el("p", { class: "sub", text: "No rule can fire yet. Flip a switch." }));
    }
    out.push(el("h3", { text: "Backward chaining: can exit_light_on be proved?" }));
    const proof = el("div", { class: "proof", role: "group", "aria-label": "Proof tree" });
    ev.proof.lines.forEach((l) => {
      const line = el("div", null, l.prefix, l.fact);
      if (l.via) line.append(" \u2190 ", el("span", { class: "rule-id", text: l.via }));
      if (l.status === "known") line.append(" ", el("span", { class: "known", text: "known" }));
      if (l.status === "missing") line.append(" ", el("span", { class: "missing", text: "missing" }));
      proof.append(line);
    });
    out.push(proof);
    const v = ev.verdict;
    out.push(resultBox(v.level, v.title, [v.text]));
    const solved = state.ai["3"];
    if (solved) out.push(resultBox(solved.found ? "info" : "error", "AI solve: " + solved.headline, [solved.detail]));
    return out;
  }

  // ------------------------------------------------------------------
  // Rendering: right column
  // ------------------------------------------------------------------
  function renderSide() {
    const out = [el("h3", { text: "Inventory", style: "margin-top:0" })];
    state.inventory.forEach((it) => {
      const body = [el("img", { src: it.icon, alt: "" }), el("span", null, el("b", { text: it.name }), el("small", { text: it.detail }))];
      out.push(it.collected
        ? el("button", { type: "button", class: "item has", "data-action": "inspect", "data-item": it.id, "data-key": "inspect-" + it.id, "aria-label": "Inspect " + it.name, disabled: ui.busy }, body)
        : el("div", { class: "item" }, body));
    });

    if (state.current_room === 3) {
      const keycard = state.inventory.find((i) => i.id === "keycard").collected;
      out.push(el("hr", { class: "section-sep" }), el("h3", { text: "Facts from earlier rooms", style: "margin-top:0" }),
        el("div", { class: "fact" }, el("span", { class: "mark " + (keycard ? "yes" : "miss"), "aria-hidden": "true", text: keycard ? "\u2713" : "\u2715" }), "has_keycard"),
        el("div", { class: "fact" }, el("span", { class: "mark " + (state.safe.unlocked ? "yes" : "miss"), "aria-hidden": "true", text: state.safe.unlocked ? "\u2713" : "\u2715" }), "safe_unlocked"));
    }

    out.push(el("hr", { class: "section-sep" }), el("h3", { text: "Objectives", style: "margin-top:0" }));
    const list = el("ul", { class: "obj" });
    state.objectives.filter((o) => o.room === state.current_room).forEach((o) => {
      list.append(el("li", { class: (o.done ? "done" : "") + (o.missed ? " missed" : "") },
        el("span", { class: "box", "aria-hidden": "true", text: o.done ? "\u2713" : o.missed ? "\u2715" : "" }),
        el("span", null, o.label, o.optional ? el("span", { class: "opt", text: o.missed ? "(missed)" : "(bonus)" }) : null),
        el("span", { class: "sr-only", text: o.done ? "done" : "not done" })));
    });
    out.push(list);

    if (state.hint && state.hint.room === state.current_room) {
      out.push(el("div", { class: "hint-box" }, el("b", { text: "Hint: " }), state.hint.text));
    }

    if (state.current_room === 1) {
      out.push(el("hr", { class: "section-sep" }), el("h3", { text: "Move yourself", style: "margin-top:0" }));
      const off = state.maze.complete;
      out.push(el("div", { class: "pad", role: "group", "aria-label": "Move" },
        padButton("up", "\u2191", off), padButton("left", "\u2190", off), padButton("down", "\u2193", off), padButton("right", "\u2192", off)));
    }
    if (state.current_room === 2 && state.safe.tries.length) {
      out.push(el("hr", { class: "section-sep" }), el("h3", { text: "Your tries", style: "margin-top:0" }));
      const tries = el("ul", { class: "tries" });
      state.safe.tries.slice().reverse().slice(0, 8).forEach((t) => tries.append(el("li", null, el("b", { text: t.code }), el("span", { text: t.message }))));
      out.push(tries);
    }
    $("#side-panel").replaceChildren(...out);
  }

  function padButton(dir, glyph, off) {
    return el("button", { type: "button", class: dir, "data-action": "move", "data-dir": dir, "data-key": "move-" + dir, "aria-label": "Move " + dir, disabled: ui.busy || off }, glyph);
  }

  // ------------------------------------------------------------------
  // Rendering: dashboard
  // ------------------------------------------------------------------
  function renderDash() {
    const o = state.output;
    const box = $("#output");
    box.className = "output " + o.level;
    box.textContent = o.text;

    $("#knowledge").replaceChildren(...state.knowledge.map((f) => el("li", { text: f })));

    const done = state.objectives.filter((o2) => !o2.optional && o2.done).length;
    const total = state.objectives.filter((o2) => !o2.optional).length;
    const items = state.objectives.map((o2) => el("li", null, (o2.done ? "\u2713 " : o2.missed ? "\u2715 " : "\u25CB "), o2.label, o2.optional ? " (bonus)" : ""));
    $("#progress").replaceChildren(
      el("div", { class: "prog-num", text: state.mission.progress + "%" }),
      el("div", { class: "bar", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": state.mission.progress, "aria-label": "Mission progress" },
        el("div", { style: "width:" + state.mission.progress + "%" })),
      el("p", { class: "sub", text: state.mission.rooms_done + " of 4 stages complete. " + done + " of " + total + " objectives done. Status: " + state.mission.status + "." }),
      el("ul", { class: "prog-list" }, items));

    const log = $("#log");
    log.replaceChildren(...state.log.map((e) => el("li", { class: e.level },
      el("span", { class: "t", text: "[" + e.time + "]" }),
      el("span", { class: "lvl", text: e.level === "success" ? "OK" : e.level === "error" ? "ERROR" : "INFO" }), e.text)));
    if (state.log.length !== ui.logCount) {
      log.scrollTop = log.scrollHeight;
      ui.logCount = state.log.length;
    }
  }

  function renderWin() {
    const show = state.mission.complete && !ui.winDismissed;
    const win = $("#win");
    if (show && win.hidden) {
      $("#win-text").textContent = "You escaped in " + fmtTime(state.stats.elapsed) + " with " + state.stats.moves +
        " moves and " + state.stats.hints + " hint(s). Every stage was verified by the server.";
      win.hidden = false;
      $("#win-again").focus();
    } else if (!show) {
      win.hidden = true;
    }
  }

  // ------------------------------------------------------------------
  // Render everything (keeps keyboard focus)
  // ------------------------------------------------------------------
  function render() {
    if (!state) return;
    const active = document.activeElement;
    const focusKey = (active && active.dataset && active.dataset.key) || ui.pendingFocus;
    renderHud();
    renderStepper();
    renderRoom();
    renderAI();
    renderSide();
    renderDash();
    renderWin();
    if (focusKey && $("#win").hidden) {
      const again = document.querySelector('[data-key="' + focusKey + '"]');
      if (again && !again.disabled) again.focus();
    }
    maybeFetchClues();
  }

  /** Entering Room 2 shows the clue paper: tell the server the clues were read (once). */
  async function maybeFetchClues() {
    if (!state || ui.clueFetching || ui.busy) return;
    if (state.current_room === 2 && state.safe.available && !state.safe.clues_read) {
      ui.clueFetching = true;
      try {
        const data = await api("/api/safe");
        if (data.state) { applyState(data.state); }
      } catch (err) { /* the page still works without this call */ }
      ui.clueFetching = false;
      if (state.safe.clues_read) render();
    }
  }

  // ------------------------------------------------------------------
  // Events (one delegated listener each, attached once)
  // ------------------------------------------------------------------
  function readDigits() {
    return ui.digits.join("");
  }

  async function handleAction(action, data) {
    switch (action) {
      case "goto": return act(() => api("/api/navigate", "POST", { room: Number(data.room) }));
      case "algo": return act(() => api("/api/maze/algorithm", "POST", { algorithm: data.algo }));
      case "maze-solve": return act(() => api("/api/maze/solve", "POST", { algorithm: state.maze.algorithm }));
      case "maze-apply": return act(() => api("/api/maze/apply", "POST", { algorithm: state.maze.algorithm }));
      case "move": return act(() => api("/api/maze/move", "POST", { direction: data.dir }));
      case "hint": return act(() => api("/api/hint", "POST", {}));
      case "inspect": return act(() => api("/api/inspect", "POST", { item: data.item }));
      case "safe-try": {
        const code = readDigits();
        if (!/^[0-9]{3}$/.test(code)) {
          localMessage("error", "Enter exactly three digits (0-9) before pressing Try code.");
          const first = document.querySelector('.digit:not(:disabled)');
          const empty = [...document.querySelectorAll(".digit")].find((d) => !d.value);
          (empty || first) && (empty || first).focus();
          return null;
        }
        return act(() => api("/api/safe/check", "POST", { code: code }));
      }
      case "safe-solve": return act(() => api("/api/safe/solve"));
      case "safe-apply": return act(() => api("/api/safe/apply", "POST", {}));
      case "sw-toggle": return act(() => api("/api/switches/toggle", "POST", { switch: data.name }));
      case "sw-check": return act(() => api("/api/switches/check", "POST", {}));
      case "sw-solve": return act(() => api("/api/switches/solve"));
      case "sw-apply": return act(() => api("/api/switches/apply", "POST", {}));
      case "exit-open": return act(() => api("/api/exit/open", "POST", {}));
      default: return null;
    }
  }

  document.addEventListener("click", (event) => {
    const target = event.target.closest("[data-action]");
    if (!target || target.disabled || !state) return;
    handleAction(target.dataset.action, target.dataset);
  });

  document.addEventListener("input", (event) => {
    const input = event.target;
    if (!input.classList || !input.classList.contains("digit")) return;
    const i = Number(input.dataset.index);
    const clean = input.value.replace(/[^0-9]/g, "").slice(-1);
    input.value = clean;
    ui.digits[i] = clean;
    if (clean && i < 2) {
      const next = document.querySelector('.digit[data-index="' + (i + 1) + '"]');
      if (next) next.focus();
    }
  });

  document.addEventListener("keydown", (event) => {
    const t = event.target;
    if (t.classList && t.classList.contains("digit")) {
      const i = Number(t.dataset.index);
      if (event.key === "Backspace" && !t.value && i > 0) {
        const prev = document.querySelector('.digit[data-index="' + (i - 1) + '"]');
        if (prev) { prev.focus(); prev.select(); }
      } else if (event.key === "Enter") {
        event.preventDefault();
        handleAction("safe-try", {});
      }
      return;
    }
    // Arrow keys move the player in Room 1 (not while typing in a field).
    const arrows = { ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right" };
    if (!arrows[event.key] || !state || state.current_room !== 1 || state.maze.complete || ui.busy) return;
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT") return;
    event.preventDefault();
    handleAction("move", { dir: arrows[event.key] });
  });

  $("#restart-btn").addEventListener("click", () => {
    if (!state) return;
    if (!ui.restartArmed) {
      ui.restartArmed = true;
      clearTimeout(ui.restartTimer);
      ui.restartTimer = setTimeout(() => { ui.restartArmed = false; if (state) renderHud(); }, 4000);
      renderHud();
      return;
    }
    clearTimeout(ui.restartTimer);
    ui.restartArmed = false;
    restartGame();
  });

  async function restartGame() {
    ui.digits = ["", "", ""];
    ui.winDismissed = false;
    ui.logCount = 0;
    await act(() => api("/api/reset", "POST", {}));
  }

  $("#win-again").addEventListener("click", restartGame);
  $("#win-close").addEventListener("click", () => { ui.winDismissed = true; $("#win").hidden = true; });
  $("#net-retry").addEventListener("click", () => { loadState(); });

  // ------------------------------------------------------------------
  // Start
  // ------------------------------------------------------------------
  async function loadState() {
    try {
      const data = await api("/api/state");
      applyState(data.state);
      $("#main").setAttribute("aria-busy", "false");
      render();
    } catch (err) {
      if (!err.network) showNetError(err.message);
    }
  }

  setInterval(updateTimer, 500);
  loadState();
})();
