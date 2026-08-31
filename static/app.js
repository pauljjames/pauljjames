"use strict";

// Kept in step with VERSION in app.py. The browser reads this file fresh on
// every load but the routes live in the running server, so a new front end can
// meet an old one. This is what lets the page say so.
const APP_VERSION = "2026-09-01.1";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
              "Saturday", "Sunday"];

const DAY_VAR = {
  Monday: "--mon", Tuesday: "--tue", Wednesday: "--wed", Thursday: "--thu",
  Friday: "--fri", Saturday: "--sat", Sunday: "--sun",
};

const dayColour = (day) => `var(${DAY_VAR[day] || "--quiet"})`;

// One colour per person, assigned by their place in the staff list, so the
// planner reads like a chart rather than a table of names.
const PEOPLE_COLOURS = 8;

let state = null;
let staffColour = {};

// ------------------------------------------------------------ small helpers

const $ = (sel) => document.querySelector(sel);
const main = () => $("#main");

function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value;
    else if (key === "style") node.setAttribute("style", value);
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

function toast(message, isError = false) {
  const note = el("div", { class: `toast ${isError ? "bad" : ""}`, text: message });
  document.body.append(note);
  setTimeout(() => note.remove(), isError ? 6000 : 3000);
}

async function api(method, path, body) {
  const options = { method };
  if (body instanceof FormData) {
    options.body = body;
  } else if (body !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(body);
  }
  const reply = await fetch(path, options);
  let payload = null;
  try { payload = await reply.json(); } catch { /* no body */ }

  if (!reply.ok) {
    const detail = payload && payload.detail;
    const error = new Error(
      (detail && (detail.message || detail)) || `${reply.status} on ${path}`
    );
    error.status = reply.status;
    error.detail = detail;
    throw error;
  }
  return payload;
}

const staffName = (id) => {
  if (!id) return "Nobody";
  const person = state.staff.find((s) => s.id === id);
  return person ? person.name : id;
};

const weekNumbers = () => state.weeks.map((w) => w.number);

const shortDate = (iso) =>
  new Date(iso + "T00:00:00").toLocaleDateString("en-NZ",
    { day: "numeric", month: "short" });

const hours = (mins) => (mins / 60).toFixed(1).replace(/\.0$/, "");

/** "1-6, 8, 10-12" — how people write a set of weeks. */
function weekRanges(weeks) {
  if (!weeks || !weeks.length) return "none";
  const sorted = [...weeks].sort((a, b) => a - b);
  const parts = [];
  let first = sorted[0];
  let last = sorted[0];
  for (const week of sorted.slice(1)) {
    if (week === last + 1) { last = week; continue; }
    parts.push(first === last ? `${first}` : `${first}-${last}`);
    first = last = week;
  }
  parts.push(first === last ? `${first}` : `${first}-${last}`);
  return parts.join(", ");
}

function assignColours() {
  staffColour = {};
  state.staff.forEach((person, index) => {
    staffColour[person.id] = `var(--p${index % PEOPLE_COLOURS})`;
  });
}

const personColour = (id) => staffColour[id] || "var(--quiet)";

function dayDot(day) {
  return el("span", {
    class: "dot",
    style: `background:${dayColour(day)}`,
    title: day || "",
  });
}

function dayKey() {
  return el("div", { class: "daykey" },
    DAYS.slice(0, 5).map((day) =>
      el("span", {}, dayDot(day), el("span", { text: day }))));
}

// ------------------------------------------------------------ loading

async function refresh() {
  state = await api("GET", "/api/state");
  assignColours();
  renderChrome();
  render();
}

function staleServerBanner() {
  if (!state || state.version === APP_VERSION) return null;
  return el("div", { class: "issues stale" },
    el("strong", { text: "The server is running an older version of this tool. " }),
    "Stop it and run python app.py again. ",
    el("span", { class: "muted", text: `Page ${APP_VERSION}, server ${state.version}.` }));
}

function renderChrome() {
  const weeks = state.weeks;
  $("#term").textContent = weeks.length
    ? `${weeks.length} teaching weeks, ${shortDate(weeks[0].starts)} to ${shortDate(weeks[weeks.length - 1].ends)}`
    : "No teaching calendar yet";

  const cover = state.coverage;
  const gaps = cover.total - cover.covered;
  const verdict = $("#verdict");

  if (state.problems.length) {
    verdict.textContent = `${state.problems.length} clash${state.problems.length > 1 ? "es" : ""}`;
    verdict.className = "verdict bad";
  } else if (gaps) {
    verdict.textContent = `${cover.percent}% staffed`;
    verdict.className = "verdict warn";
  } else {
    verdict.textContent = "Fully staffed";
    verdict.className = "verdict good";
  }
  verdict.onclick = () => go(state.problems.length ? "planner" : "dashboard");
}

// ------------------------------------------------------------ dashboard

function dashboardView() {
  const cover = state.coverage;
  const gaps = cover.total - cover.covered;

  const tiles = el("div", { class: "tiles" },
    tile(`${cover.percent}%`, "of class weeks staffed",
      cover.percent === 100 ? "good" : "warn"),
    tile(gaps, gaps === 1 ? "class week needs somebody" : "class weeks need somebody",
      gaps ? "warn" : "good"),
    tile(state.staff.length, state.staff.length === 1 ? "person" : "people"),
    tile(state.problems.length,
      state.problems.length === 1 ? "clash to sort out" : "clashes to sort out",
      state.problems.length ? "bad" : "good"),
  );

  return el("div", {}, staleServerBanner(), tiles, issuesPanel(),
    el("div", { class: "columns" }, needsSomebodyPanel(), utilisationPanel()));
}

function tile(value, label, tone = "") {
  return el("div", { class: `tile ${tone}` },
    el("div", { class: "figure", text: String(value) }),
    el("div", { class: "label", text: label }));
}

function needsSomebodyPanel() {
  const rows = state.coverage.rows;
  const panel = el("section", { class: "panel" },
    el("h2", { text: "Needs somebody" }));

  if (!rows.length) {
    panel.append(el("p", { class: "hint" },
      state.timetable.length
        ? "Every class that runs has somebody on it."
        : "No timetable yet. Import one from Setup."));
    return panel;
  }

  panel.append(el("p", { class: "hint" },
    "Classes with nobody on them. That can be deliberate, if another team ",
    "teaches them. Click one to staff it."));

  const table = el("table", {},
    el("thead", {}, el("tr", {},
      el("th", { text: "Class" }), el("th", { text: "Day" }),
      el("th", { text: "Weeks" }), el("th", {}))));

  const body = el("tbody");
  for (const row of rows) {
    body.append(el("tr", {},
      el("td", {}, el("strong", { text: `${row.course_code} ${row.section}` }),
        row.course_title ? el("div", { class: "muted", text: row.course_title }) : null),
      el("td", {}, dayDot(row.day), row.day || "—"),
      el("td", { text: weekRanges(row.weeks) },),
      el("td", { class: "right" },
        row.timetable_row_id
          ? el("button", {
              class: "action",
              onclick: () => { go("planner"); openAssign(row.timetable_row_id); },
              text: "Staff it",
            })
          : el("span", { class: "muted", text: "added class" }))));
  }
  table.append(body);
  panel.append(table);
  return panel;
}

function utilisationPanel() {
  const panel = el("section", { class: "panel" }, el("h2", { text: "Who is carrying what" }));

  if (!state.staff.length) {
    panel.append(el("p", { class: "hint", text: "No staff yet. Add them on Setup." }));
    return panel;
  }

  const teachingWeeks = weekNumbers().length || 1;
  panel.append(el("p", { class: "hint" },
    "Average contact hours a week across the semester, against a target where ",
    "one is set."));

  const list = el("div", { class: "bars" });
  const peak = Math.max(1, ...state.staff.map((s) => averageMinutes(s.id)));

  for (const person of state.staff) {
    const average = averageMinutes(person.id);
    const target = person.target_minutes;
    const spikes = state.over_target.filter((o) => o.staff_id === person.id);
    const over = target && average > target;
    const width = Math.round((average / peak) * 100);

    list.append(el("div", { class: "bar-row" },
      el("div", { class: "bar-name" },
        el("span", { class: "swatch", style: `background:${personColour(person.id)}` }),
        person.name),
      el("div", { class: "bar-track" },
        el("div", {
          class: `bar-fill ${over ? "over" : ""}`,
          style: `width:${width}%; background:${over ? "var(--clash)" : personColour(person.id)}`,
        }),
        target
          ? el("div", {
              class: "bar-target",
              style: `left:${Math.min(100, Math.round((target / peak) * 100))}%`,
              title: `Target ${hours(target)} hours`,
            })
          : null),
      el("div", { class: "bar-value" },
        `${hours(average)} h`,
        target ? el("span", { class: "muted", text: ` of ${hours(target)}` }) : null),
      el("div", { class: "bar-note" },
        spikes.length
          ? el("span", {
              class: "flag warn",
              text: `over in ${weekRanges(spikes.map((o) => o.week))}`,
            })
          : null)));
  }

  panel.append(list);
  return panel;

  function averageMinutes(id) {
    const byWeek = state.load[id] || {};
    const total = Object.values(byWeek).reduce((sum, m) => sum + m, 0);
    return total / teachingWeeks;
  }
}

// ------------------------------------------------------------ planner

let openRow = null;      // the timetable row whose assign panel is showing

function plannerView() {
  const wrap = el("div", {}, staleServerBanner(), issuesPanel(), clashPanel());

  if (!state.timetable.length) {
    wrap.append(emptyPanel("No timetable yet",
      "Import the published timetable from Setup, or add classes by hand."));
    return wrap;
  }

  const panel = el("section", { class: "panel" },
    el("div", { class: "toolbar" },
      el("h2", { text: "Timetable" }),
      el("span", { class: "spacer" }),
      dayKey(),
      el("button", {
        class: "action", text: "Add a class",
        onclick: () => editTimetable(null),
      })));

  panel.append(el("p", { class: "hint" },
    "The timetable is set outside this tool. What you decide is who covers it, ",
    "week by week. Nobody can be put in two places at once."));

  const table = el("table", { class: "planner" },
    el("thead", {}, el("tr", {},
      el("th", { text: "Class" }),
      el("th", { text: "When" }),
      el("th", { text: "Staffing" }),
      el("th", {}))));

  const body = el("tbody");
  for (const row of state.timetable) {
    body.append(plannerRow(row));
    if (openRow === row.id) body.append(assignRow(row));
  }
  table.append(body);
  panel.append(table);
  wrap.append(panel);
  return wrap;
}

function spansFor(rowId) {
  return state.assignments.filter((a) => a.timetable_id === rowId);
}

function plannerRow(row) {
  const spans = spansFor(row.id);
  const staffed = new Set(spans.flatMap((s) => s.weeks));
  const gaps = row.weeks.filter((w) => !staffed.has(w) && !isCancelled(row, w));
  const clashing = state.classes.some(
    (c) => c.timetable_row_id === row.id && c.clashing);

  return el("tr", { class: clashing ? "clash" : "" },
    el("td", {},
      el("strong", { text: `${row.course_code} ${row.section}` }),
      row.course_title ? el("div", { class: "muted", text: row.course_title }) : null),
    el("td", {},
      dayDot(row.day),
      `${row.day} ${row.start}–${row.end}`,
      el("div", { class: "muted", text: `weeks ${weekRanges(row.weeks)}` })),
    el("td", {}, staffingCell(row, spans, gaps)),
    el("td", { class: "right" },
      el("button", {
        class: openRow === row.id ? "action primary" : "action",
        text: openRow === row.id ? "Close" : "Assign",
        onclick: () => { openRow = openRow === row.id ? null : row.id; render(); },
      }),
      el("button", {
        class: "link", text: "Edit", onclick: () => editTimetable(row),
      })));
}

function isCancelled(row, week) {
  return state.classes.some(
    (c) => c.timetable_row_id === row.id && c.week === week && !c.runs);
}

/** Who covers this class, as named spans over a ribbon of the weeks it runs. */
function staffingCell(row, spans, gaps) {
  const cell = el("div", { class: "staffing" });

  if (!spans.length) {
    cell.append(el("span", { class: "flag warn", text: "nobody yet" }));
  } else {
    const chips = el("div", { class: "chips" });
    for (const span of spans) {
      chips.append(el("span", { class: "chip" },
        el("span", { class: "swatch", style: `background:${personColour(span.staff_id)}` }),
        staffName(span.staff_id),
        el("span", { class: "muted", text: ` ${weekRanges(span.weeks)}` })));
    }
    cell.append(chips);
    if (gaps.length) {
      cell.append(el("span", { class: "flag warn", text: `gap in ${weekRanges(gaps)}` }));
    }
  }

  cell.append(staffingRibbon(row, spans));
  return cell;
}

function staffingRibbon(row, spans) {
  const owner = {};
  for (const span of spans) for (const week of span.weeks) owner[week] = span.staff_id;

  const ribbon = el("div", { class: "ribbon" });
  for (const week of weekNumbers()) {
    const runs = row.weeks.includes(week);
    const cancelled = runs && isCancelled(row, week);
    const who = owner[week];
    const cell = el("span", {
      class: `wk ${!runs ? "off" : cancelled ? "cancelled" : who ? "" : "gap"}`,
      style: runs && !cancelled && who ? `background:${personColour(who)}` : null,
      title: !runs ? `Week ${week}: does not run`
        : cancelled ? `Week ${week}: cancelled`
        : who ? `Week ${week}: ${staffName(who)}`
        : `Week ${week}: nobody`,
    });
    ribbon.append(cell);
  }
  return ribbon;
}

// ------------------------------------------------------------ assigning

let assignScope = null;    // weeks selected in the open panel
let candidates = null;     // availability for that scope

function openAssign(rowId) {
  openRow = rowId;
  assignScope = null;
  candidates = null;
  render();
}

function assignRow(row) {
  const cell = el("td", { colspan: 4 });
  cell.append(assignPanel(row));
  return el("tr", { class: "assign-row" }, cell);
}

function assignPanel(row) {
  if (assignScope === null) assignScope = [...row.weeks];

  const panel = el("div", { class: "assign" });

  panel.append(el("div", { class: "assign-head" },
    el("h3", { text: `Who takes ${row.course_code} ${row.section}?` }),
    el("span", { class: "muted", text: `${row.day} ${row.start}–${row.end}` })));

  // 1. scope
  const scope = el("div", { class: "scope" },
    el("span", { class: "label", text: "Weeks" }),
    el("button", {
      class: sameWeeks(assignScope, row.weeks) ? "pill on" : "pill",
      text: `every week it runs (${weekRanges(row.weeks)})`,
      onclick: () => { assignScope = [...row.weeks]; candidates = null; render(); },
    }));

  const halves = splitPoints(row.weeks);
  for (const half of halves) {
    scope.append(el("button", {
      class: sameWeeks(assignScope, half.weeks) ? "pill on" : "pill",
      text: half.label,
      onclick: () => { assignScope = half.weeks; candidates = null; render(); },
    }));
  }
  panel.append(scope);

  // week ticks, so any set at all can be chosen
  const ticks = el("div", { class: "weekticks" });
  for (const week of row.weeks) {
    const on = assignScope.includes(week);
    ticks.append(el("button", {
      class: on ? "tick on" : "tick",
      text: String(week),
      onclick: () => {
        assignScope = on
          ? assignScope.filter((w) => w !== week)
          : [...assignScope, week].sort((a, b) => a - b);
        candidates = null;
        render();
      },
    }));
  }
  panel.append(ticks);

  if (!assignScope.length) {
    panel.append(el("p", { class: "hint", text: "Pick at least one week." }));
    return panel;
  }

  // 2. candidates
  if (candidates === null) {
    loadCandidates(row);
    panel.append(el("p", { class: "hint", text: "Looking at who is free…" }));
    return panel;
  }

  panel.append(el("p", { class: "hint" },
    "People already teaching something else at this time are greyed out, so a ",
    "clash cannot be made by accident."));

  const free = candidates.filter((p) => p.free);
  const busy = candidates.filter((p) => !p.free);
  const list = el("div", { class: "candidates" });

  for (const person of [...free, ...busy]) {
    list.append(candidateCard(row, person));
  }
  panel.append(list);

  const held = spansFor(row.id).filter((s) =>
    s.weeks.some((w) => assignScope.includes(w)));
  if (held.length) {
    panel.append(el("div", { class: "toolbar" },
      el("button", {
        class: "link danger",
        text: `Take nobody for ${weekRanges(assignScope)}`,
        onclick: () => unassign(row),
      })));
  }

  return panel;
}

function candidateCard(row, person) {
  // Per week, because the target is per week. A semester total beside a weekly
  // target invites the wrong comparison.
  const perWeek = person.minutes / (weekNumbers().length || 1);
  const target = person.target_minutes;

  if (!person.free) {
    return el("div", { class: "cand busy" },
      el("div", { class: "cand-name" },
        el("span", { class: "swatch", style: `background:${personColour(person.id)}` }),
        person.name),
      el("div", { class: "cand-why", text: `busy in ${weekRanges(person.busy_weeks)}` }));
  }

  return el("button", {
    class: "cand",
    onclick: () => assignTo(row, person),
  },
    el("div", { class: "cand-name" },
      el("span", { class: "swatch", style: `background:${personColour(person.id)}` }),
      person.name),
    el("div", { class: "cand-why" },
      `${hours(perWeek)} h a week`,
      target
        ? el("span", {
            class: perWeek > target ? "over" : "muted",
            text: ` of ${hours(target)}`,
          })
        : null));
}

function splitPoints(weeks) {
  if (weeks.length < 4) return [];
  const middle = Math.ceil(weeks.length / 2);
  const first = weeks.slice(0, middle);
  const second = weeks.slice(middle);
  return [
    { label: `weeks ${weekRanges(first)}`, weeks: first },
    { label: `weeks ${weekRanges(second)}`, weeks: second },
  ];
}

const sameWeeks = (a, b) =>
  a.length === b.length && a.every((w, i) => w === b[i]);

async function loadCandidates(row) {
  try {
    const reply = await api("POST", "/api/availability", {
      day: row.day, start: row.start, end: row.end,
      weeks: assignScope, timetable_id: row.id,
    });
    candidates = reply.staff;
    render();
  } catch (error) {
    toast(error.message, true);
  }
}

async function assignTo(row, person, replace = false) {
  try {
    await api("POST", "/api/assign", {
      timetable_id: row.id, staff_id: person.id,
      weeks: assignScope, replace,
    });
    toast(`${person.name} takes ${row.course_code} ${row.section}, weeks ${weekRanges(assignScope)}.`);
    openRow = null;
    assignScope = null;
    candidates = null;
    await refresh();
  } catch (error) {
    if (error.status === 409 && error.detail && error.detail.error === "already_assigned") {
      const ok = await confirmDialog(
        "Hand this over?",
        `${error.detail.message} Give those weeks to ${person.name} instead?`);
      if (ok) await assignTo(row, person, true);
      return;
    }
    // The picker greys out anyone who would clash, so this is a last defence.
    toast(error.message, true);
    candidates = null;
    render();
  }
}

async function unassign(row) {
  try {
    await api("POST", "/api/unassign", {
      timetable_id: row.id, weeks: assignScope,
    });
    toast(`Nobody on ${row.course_code} ${row.section} for weeks ${weekRanges(assignScope)}.`);
    candidates = null;
    await refresh();
  } catch (error) {
    toast(error.message, true);
  }
}

// ------------------------------------------------------------ clashes

function clashPanel() {
  if (!state.problems.length) return null;

  const panel = el("section", { class: "panel clashlist" },
    el("h2", { text: state.problems.length === 1 ? "A clash" : "Clashes" }),
    el("p", { class: "hint" },
      "Assignments are checked before they are made, so these came in with the ",
      "data rather than from staffing. Reassign one side of each pair."));

  for (const problem of state.problems) {
    panel.append(el("div", { class: "clashrow" },
      el("strong", { text: staffName(problem.staff_id) }),
      " is in two places in ",
      el("strong", { text: `week${problem.weeks.length > 1 ? "s" : ""} ${weekRanges(problem.weeks)}` }),
      ": ",
      el("span", { class: "klass", text: problem.a.label }),
      " and ",
      el("span", { class: "klass", text: problem.b.label }),
      problem.a.timetable_row_id
        ? el("button", {
            class: "link", text: "Fix",
            onclick: () => openAssign(problem.a.timetable_row_id),
          })
        : null));
  }
  return panel;
}

// ------------------------------------------------------------ staff view

function staffView() {
  const wrap = el("div", {}, staleServerBanner());

  if (!state.staff.length) {
    wrap.append(emptyPanel("No staff yet", "Add people on the Setup page."));
    return wrap;
  }

  wrap.append(el("div", { class: "toolbar" }, dayKey()));

  for (const person of state.staff) {
    const mine = state.classes.filter((c) => c.staff_id === person.id);
    const byWeek = new Map();
    for (const c of mine) {
      if (!byWeek.has(c.week)) byWeek.set(c.week, []);
      byWeek.get(c.week).push(c);
    }

    const panel = el("section", { class: "panel" },
      el("div", { class: "toolbar" },
        el("h2", {},
          el("span", { class: "swatch", style: `background:${personColour(person.id)}` }),
          person.name),
        el("span", { class: "spacer" }),
        el("span", { class: "muted", text: `${mine.filter((c) => c.runs).length} classes` })));

    const grid = el("div", { class: "weeks" });
    for (const week of state.weeks) {
      const classes = (byWeek.get(week.number) || [])
        .sort((a, b) => DAYS.indexOf(a.day) - DAYS.indexOf(b.day) ||
                        String(a.start).localeCompare(String(b.start)));
      grid.append(el("div", { class: "week" },
        el("div", { class: "week-head" },
          el("strong", { text: `Week ${week.number}` }),
          el("span", { class: "muted", text: shortDate(week.starts) }),
          week.note ? el("div", { class: "muted note", text: week.note }) : null),
        classes.length
          ? classes.map(classCard)
          : el("div", { class: "empty", text: "nothing timetabled" })));
    }
    panel.append(grid);
    wrap.append(panel);
  }

  wrap.append(el("p", { class: "hint" },
    "Teaching outside this timetable is not tracked, so an empty week here does ",
    "not mean that person is free."));
  return wrap;
}

function classCard(c) {
  const status = !c.runs ? "cancelled" : c.status === "Changed" ? "changed"
    : c.status === "Added" ? "added" : "";
  return el("div", {
    class: `klass ${status} ${c.clashing ? "clash" : ""}`,
    style: `border-left-color:${dayColour(c.day)}`,
  },
    el("div", { class: "klass-label" }, c.label,
      c.clashing ? el("span", { class: "badge bad", text: "clash" }) : null),
    el("div", { class: "muted" },
      c.runs ? `${c.day} ${c.start}–${c.end}` : "cancelled"),
    c.status === "Added" ? el("span", { class: "badge", text: "added" }) : null,
    c.status === "Changed" ? el("span", { class: "badge", text: "changed" }) : null);
}

// ------------------------------------------------------------ load

function loadView() {
  const wrap = el("div", {}, staleServerBanner());
  const weeks = weekNumbers();

  if (!state.staff.length || !weeks.length) {
    wrap.append(emptyPanel("Nothing to add up yet",
      "Add staff and a teaching calendar on Setup."));
    return wrap;
  }

  const panel = el("section", { class: "panel" },
    el("h2", { text: "Contact hours" }),
    el("p", { class: "hint" },
      "Timetabled hours only, so this will not match a workload allocation that ",
      "also covers supervision, marking and admin. A red figure is over that ",
      "person's target."));

  const table = el("table", { class: "loadtable" });
  table.append(el("thead", {}, el("tr", {},
    el("th", { text: "Person" }),
    weeks.map((w) => el("th", { class: "num", text: String(w) })),
    el("th", { class: "num", text: "Total" }),
    el("th", { class: "num", text: "Target" }))));

  const body = el("tbody");
  for (const person of state.staff) {
    const byWeek = state.load[person.id] || {};
    const total = Object.values(byWeek).reduce((sum, m) => sum + m, 0);
    const target = person.target_minutes;

    body.append(el("tr", {},
      el("td", {},
        el("span", { class: "swatch", style: `background:${personColour(person.id)}` }),
        person.name),
      weeks.map((week) => {
        const minutes = byWeek[week] || 0;
        const over = target && minutes > target;
        return el("td", {
          class: `num ${over ? "over" : ""} ${minutes ? "" : "zero"}`,
          title: over ? `Over target by ${hours(minutes - target)} hours` : "",
          text: minutes ? hours(minutes) : "·",
        });
      }),
      el("td", { class: "num strong", text: hours(total) }),
      el("td", { class: "num muted", text: target ? hours(target) : "—" })));
  }
  table.append(body);
  panel.append(table);
  wrap.append(panel);
  return wrap;
}

// ------------------------------------------------------------ exceptions

function exceptionsView() {
  const wrap = el("div", {}, staleServerBanner(), issuesPanel());

  const panel = el("section", { class: "panel" },
    el("div", { class: "toolbar" },
      el("h2", { text: "Exceptions" }),
      el("span", { class: "spacer" }),
      el("button", {
        class: "action", text: "Add an exception",
        onclick: () => editException(null),
      })));

  panel.append(el("p", { class: "hint" },
    "Single weeks that depart from the timetable. Not for staffing: if somebody ",
    "else is taking a week, assign that week to them on the Planner."));

  if (!state.exceptions.length) {
    panel.append(el("p", { class: "empty", text: "No exceptions." }));
    wrap.append(panel);
    return wrap;
  }

  const table = el("table", {},
    el("thead", {}, el("tr", {},
      el("th", { text: "Week" }), el("th", { text: "Class" }),
      el("th", { text: "What" }), el("th", { text: "Note" }), el("th", {}))));

  const body = el("tbody");
  for (const exc of state.exceptions) {
    body.append(el("tr", {},
      el("td", { text: String(exc.week) }),
      el("td", { text: `${exc.course_code} ${exc.section}` }),
      el("td", {},
        el("span", { class: `badge ${exc.action.toLowerCase()}`, text: exc.action }),
        " ", describeOverride(exc)),
      el("td", { class: "muted", text: exc.note || "" }),
      el("td", { class: "right" },
        el("button", { class: "link", text: "Edit", onclick: () => editException(exc) }))));
  }
  table.append(body);
  panel.append(table);
  wrap.append(panel);
  return wrap;
}

function describeOverride(x) {
  const bits = [];
  if (x.day) bits.push(x.day);
  if (x.start || x.end) bits.push(`${x.start || "?"}–${x.end || "?"}`);
  if (x.action === "Add" && x.staff_id) bits.push(staffName(x.staff_id));
  return bits.length ? bits.join(" ") : (x.action === "Cancel" ? "" : "no change given");
}

// ------------------------------------------------------------ setup

function setupView() {
  const wrap = el("div", {}, staleServerBanner(), issuesPanel());

  // staff
  const staffPanel = el("section", { class: "panel" },
    el("div", { class: "toolbar" },
      el("h2", { text: "Staff" }),
      el("span", { class: "spacer" }),
      el("button", { class: "action", text: "Add somebody", onclick: () => editStaff(null) })));

  staffPanel.append(el("p", { class: "hint" },
    "The people you are responsible for. A target is contact hours a week, and ",
    "is optional."));

  if (state.staff.length) {
    const table = el("table", {},
      el("thead", {}, el("tr", {},
        el("th", { text: "Name" }), el("th", { text: "Id" }),
        el("th", { text: "Email" }), el("th", { class: "num", text: "Target" }),
        el("th", {}))));
    const body = el("tbody");
    for (const person of state.staff) {
      body.append(el("tr", {},
        el("td", {},
          el("span", { class: "swatch", style: `background:${personColour(person.id)}` }),
          person.name),
        el("td", { class: "muted", text: person.id }),
        el("td", { class: "muted", text: person.email || "" }),
        el("td", { class: "num muted", text: person.target_minutes ? `${hours(person.target_minutes)} h` : "—" }),
        el("td", { class: "right" },
          el("button", { class: "link", text: "Edit", onclick: () => editStaff(person) }))));
    }
    table.append(body);
    staffPanel.append(table);
  } else {
    staffPanel.append(el("p", { class: "empty", text: "Nobody yet." }));
  }
  wrap.append(staffPanel);

  wrap.append(importPanel());

  // weeks
  const weeksPanel = el("section", { class: "panel" },
    el("div", { class: "toolbar" },
      el("h2", { text: "Teaching calendar" }),
      el("span", { class: "spacer" }),
      el("button", { class: "action", text: "Add a week", onclick: addWeek }),
      state.weeks.length
        ? el("button", { class: "link danger", text: "Remove the last week", onclick: removeLastWeek })
        : null));

  weeksPanel.append(el("p", { class: "hint" },
    "Weeks are numbered consecutively through teaching, so a mid semester break ",
    "is a gap between dates rather than an extra week."));

  if (state.weeks.length) {
    const table = el("table", {},
      el("thead", {}, el("tr", {},
        el("th", { text: "Week" }), el("th", { text: "Monday" }),
        el("th", { text: "Ends" }), el("th", { text: "Note" }))));
    const body = el("tbody");
    for (const week of state.weeks) {
      body.append(el("tr", {},
        el("td", { text: String(week.number) }),
        el("td", {}, el("input", {
          type: "date", value: week.starts,
          onchange: (e) => saveWeek(week.number, "starts", e.target.value),
        })),
        el("td", { class: "muted", text: shortDate(week.ends) }),
        el("td", {}, el("input", {
          type: "text", value: week.note || "", placeholder: "—",
          onchange: (e) => saveWeek(week.number, "note", e.target.value),
        }))));
    }
    table.append(body);
    weeksPanel.append(table);
  } else {
    weeksPanel.append(el("p", { class: "empty", text: "No weeks yet." }));
  }
  wrap.append(weeksPanel);

  // data
  wrap.append(el("section", { class: "panel" },
    el("h2", { text: "Sample data" }),
    el("p", { class: "hint" },
      "The sample timetable shows the states this tool distinguishes: a split ",
      "semester, a section nobody covers, a cancelled week and an added class."),
    el("div", { class: "toolbar" },
      el("button", {
        class: "action", text: "Reload the sample data",
        onclick: () => confirmThen(
          "Replace everything with the sample data?",
          () => api("POST", "/api/sample-data"), "Sample data loaded."),
      }),
      el("button", {
        class: "link danger", text: "Clear everything",
        onclick: () => confirmThen(
          "Delete all staff, timetable, staffing and exceptions?",
          () => api("DELETE", "/api/all-data"), "Everything cleared."),
      }))));

  return wrap;
}

// ------------------------------------------------------------ import

let importPreview = null;

function importPanel() {
  const panel = el("section", { class: "panel" },
    el("h2", { text: "Import a timetable" }));

  panel.append(el("p", { class: "hint" },
    "A CSV or Excel file with a header row and columns for course code, section, ",
    "day, start, end and weeks. Weeks can be written 1-6, 8, 10-12. Staffing is ",
    "kept wherever the same class still runs in the same week."));

  panel.append(el("div", { class: "toolbar" },
    el("input", {
      type: "file", id: "importfile", accept: ".csv,.tsv,.xlsx,.xlsm",
      onchange: (e) => previewImport(e.target.files[0]),
    })));

  if (!importPreview) return panel;

  const { rows, issues, would_drop: drop } = importPreview;

  if (issues.length) {
    panel.append(el("div", { class: "issues" },
      el("strong", { text: issues.length === 1 ? "One row could not be read" : `${issues.length} rows could not be read` }),
      el("ul", {}, issues.map((i) => el("li", { text: i })))));
  }

  panel.append(el("p", {},
    el("strong", { text: `${rows.length} classes read.` }),
    ` They would replace the ${importPreview.replacing} now in the timetable.`));

  if (drop.length) {
    panel.append(el("div", { class: "issues" },
      el("strong", { text: `${drop.length} staffed week${drop.length > 1 ? "s" : ""} would be lost` }),
      el("p", { class: "hint", text: "These classes are not in the new file, or not in those weeks." }),
      el("ul", {}, drop.slice(0, 12).map((d) =>
        el("li", { text: `${d.course_code} ${d.section} week ${d.week}: ${staffName(d.staff_id)}` }))),
      drop.length > 12 ? el("p", { class: "muted", text: `and ${drop.length - 12} more.` }) : null));
  }

  if (rows.length) {
    const table = el("table", {},
      el("thead", {}, el("tr", {},
        el("th", { text: "Class" }), el("th", { text: "Day" }),
        el("th", { text: "Time" }), el("th", { text: "Weeks" }))));
    const body = el("tbody");
    for (const row of rows.slice(0, 40)) {
      body.append(el("tr", {},
        el("td", { text: `${row.course_code} ${row.section}` }),
        el("td", {}, dayDot(row.day), row.day),
        el("td", { text: `${row.start}–${row.end}` }),
        el("td", { text: weekRanges(row.weeks) })));
    }
    table.append(body);
    panel.append(table);
    if (rows.length > 40) {
      panel.append(el("p", { class: "muted", text: `and ${rows.length - 40} more.` }));
    }

    panel.append(el("div", { class: "toolbar" },
      el("button", {
        class: "action primary", text: "Replace the timetable",
        onclick: () => commitImport("replace"),
      }),
      el("button", {
        class: "action", text: "Add to what is there",
        onclick: () => commitImport("append"),
      }),
      el("button", {
        class: "link", text: "Cancel",
        onclick: () => { importPreview = null; render(); },
      })));
  }

  return panel;
}

async function previewImport(file) {
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  try {
    importPreview = await api("POST", "/api/import/preview", form);
    render();
  } catch (error) {
    importPreview = null;
    toast(error.message, true);
    render();
  }
}

async function commitImport(mode) {
  if (mode === "replace") {
    const ok = await confirmDialog(
      "Replace the timetable?",
      `The ${importPreview.replacing} classes now in the timetable will be replaced by ` +
      `${importPreview.rows.length} from the file. Staffing is kept where the same class ` +
      `still runs in the same week.`);
    if (!ok) return;
  }
  try {
    const result = await api("POST", "/api/import/commit",
      { rows: importPreview.rows, mode });
    importPreview = null;
    $("#importfile") && ($("#importfile").value = "");
    toast(result.kept
      ? `Imported ${result.added} classes, keeping ${result.kept} staffed weeks.`
      : `Imported ${result.added} classes.`);
    await refresh();
  } catch (error) {
    toast(error.message, true);
  }
}

// ------------------------------------------------------------ weeks editing

async function confirmThen(question, action, done) {
  if (!(await confirmDialog("Are you sure?", question))) return;
  try {
    await action();
    toast(done);
    importPreview = null;
    openRow = null;
    await refresh();
  } catch (error) {
    toast(error.message, true);
  }
}

const sixDaysOn = (iso) => {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + 6);
  return d.toISOString().slice(0, 10);
};

async function saveWeek(number, field, value) {
  const weeks = state.weeks.map((w) => ({
    number: w.number,
    starts: w.number === number && field === "starts" ? value : w.starts,
    ends: w.number === number && field === "starts" ? sixDaysOn(value) : w.ends,
    note: w.number === number && field === "note" ? value : w.note,
  }));
  try {
    await api("PUT", "/api/weeks", { weeks });
    await refresh();
  } catch (error) {
    toast(error.message, true);
  }
}

async function addWeek() {
  const last = state.weeks[state.weeks.length - 1];
  const starts = last
    ? (() => { const d = new Date(last.starts + "T00:00:00"); d.setDate(d.getDate() + 7);
               return d.toISOString().slice(0, 10); })()
    : new Date().toISOString().slice(0, 10);
  const weeks = [
    ...state.weeks.map((w) => ({ ...w })),
    { number: (last ? last.number : 0) + 1, starts, ends: sixDaysOn(starts), note: "" },
  ];
  await api("PUT", "/api/weeks", { weeks });
  await refresh();
}

async function removeLastWeek() {
  const weeks = state.weeks.slice(0, -1).map((w) => ({ ...w }));
  await api("PUT", "/api/weeks", { weeks });
  await refresh();
}

// ------------------------------------------------------------ issues panel

function issuesPanel() {
  if (!state.issues.length) return null;
  return el("div", { class: "issues" },
    el("strong", { text: state.issues.length === 1 ? "A problem with the records" : "Problems with the records" }),
    el("ul", {}, state.issues.map((i) => el("li", { text: i }))));
}

function emptyPanel(heading, hint) {
  return el("section", { class: "panel" },
    el("h2", { text: heading }),
    el("p", { class: "hint", text: hint }));
}

// ------------------------------------------------------------ dialogs

function confirmDialog(title, question) {
  return new Promise((resolve) => {
    const dialog = $("#editor");
    $("#editor-title").textContent = title;
    const body = $("#editor-body");
    body.replaceChildren(el("p", { text: question }));
    $("#editor-delete").hidden = true;

    const save = $("#editor-save");
    save.textContent = "Yes";
    const finish = (answer) => {
      save.textContent = "Save";
      dialog.close();
      resolve(answer);
    };
    save.onclick = () => finish(true);
    $("#editor-cancel").onclick = () => finish(false);
    dialog.onclose = () => resolve(false);
    dialog.showModal();
  });
}

function openEditor(title, fields, onSave, onDelete) {
  const dialog = $("#editor");
  $("#editor-title").textContent = title;
  $("#editor-body").replaceChildren(...fields);

  const remove = $("#editor-delete");
  remove.hidden = !onDelete;
  remove.onclick = async () => {
    if (!(await confirmDialog("Delete this?", "This cannot be undone."))) return;
    try {
      await onDelete();
      dialog.close();
      openRow = null;
      await refresh();
      toast("Deleted.");
    } catch (error) { toast(error.message, true); }
  };

  $("#editor-save").textContent = "Save";
  $("#editor-save").onclick = async () => {
    try {
      await onSave();
      dialog.close();
      await refresh();
      toast("Saved.");
    } catch (error) { toast(error.message, true); }
  };
  $("#editor-cancel").onclick = () => dialog.close();
  dialog.onclose = null;
  dialog.showModal();
}

function field(label, input) {
  return el("label", { class: "field" }, el("span", { text: label }), input);
}

function textInput(id, value, opts = {}) {
  return el("input", { id, value: value ?? "", type: opts.type || "text",
                       placeholder: opts.placeholder || "" });
}

function staffSelect(id, value, { allowBlank = false, blankLabel = "" } = {}) {
  const select = el("select", { id });
  if (allowBlank) select.append(el("option", { value: "", text: blankLabel }));
  for (const person of state.staff) {
    select.append(el("option", { value: person.id, selected: person.id === value },
      person.name));
  }
  return select;
}

function daySelect(id, value, { allowBlank = false } = {}) {
  const select = el("select", { id });
  if (allowBlank) select.append(el("option", { value: "", text: "unchanged" }));
  for (const day of DAYS) {
    select.append(el("option", { value: day, selected: day === value }, day));
  }
  return select;
}

function weekTicks(id, selected) {
  const chosen = new Set(selected || []);
  const box = el("div", { class: "weekticks", id });
  for (const week of weekNumbers()) {
    const button = el("button", {
      class: chosen.has(week) ? "tick on" : "tick",
      text: String(week),
      "data-week": week,
      onclick: (e) => {
        e.preventDefault();
        const on = e.target.classList.toggle("on");
        if (on) chosen.add(week); else chosen.delete(week);
      },
    });
    box.append(button);
  }
  const tools = el("div", { class: "toolbar" },
    el("button", {
      class: "link", text: "All",
      onclick: (e) => {
        e.preventDefault();
        box.querySelectorAll(".tick").forEach((t) => t.classList.add("on"));
        weekNumbers().forEach((w) => chosen.add(w));
      },
    }),
    el("button", {
      class: "link", text: "None",
      onclick: (e) => {
        e.preventDefault();
        box.querySelectorAll(".tick").forEach((t) => t.classList.remove("on"));
        chosen.clear();
      },
    }));
  return el("div", {}, box, tools);
}

const ticked = (id) =>
  [...document.querySelectorAll(`#${id} .tick.on`)]
    .map((t) => Number(t.dataset.week)).sort((a, b) => a - b);

const val = (id) => {
  const node = document.getElementById(id);
  return node ? node.value.trim() : "";
};

const orNull = (id) => val(id) || null;

// ------------------------------------------------------------ editors

function editTimetable(row) {
  const fields = [
    field("Course code", textInput("tt-code", row?.course_code, { placeholder: "111.701" })),
    field("Course title", textInput("tt-title", row?.course_title)),
    field("Section", textInput("tt-section", row?.section, { placeholder: "A" })),
    field("Day", daySelect("tt-day", row?.day || "Monday")),
    field("Starts", textInput("tt-start", row?.start || "09:00", { type: "time" })),
    field("Ends", textInput("tt-end", row?.end || "11:00", { type: "time" })),
    field("Weeks", weekTicks("tt-weeks", row?.weeks || weekNumbers())),
    el("p", { class: "hint" },
      "The timetable is set outside this tool, so this is for corrections. Who ",
      "teaches it is decided on the Planner."),
  ];

  openEditor(row ? `${row.course_code} ${row.section}` : "A class", fields,
    () => {
      const body = {
        course_code: val("tt-code"), course_title: val("tt-title"),
        section: val("tt-section"), day: val("tt-day"),
        start: val("tt-start"), end: val("tt-end"),
        weeks: ticked("tt-weeks"),
      };
      if (!body.course_code || !body.section) throw new Error("A course code and section are needed.");
      return row
        ? api("PUT", `/api/timetable/${row.id}`, body)
        : api("POST", "/api/timetable", body);
    },
    row ? () => api("DELETE", `/api/timetable/${row.id}`) : null);
}

function editException(exc) {
  const actionSelect = el("select", { id: "ex-action" },
    ["Change", "Cancel", "Add"].map((a) =>
      el("option", { value: a, selected: exc?.action === a }, a)));

  const staffRow = field("Staff", staffSelect("ex-staff", exc?.staff_id,
    { allowBlank: true, blankLabel: "nobody yet" }));

  const showStaff = () => {
    staffRow.hidden = val("ex-action") !== "Add";
  };
  actionSelect.addEventListener("change", showStaff);

  const fields = [
    field("Week", textInput("ex-week", exc?.week ?? "", { type: "number" })),
    field("Course code", textInput("ex-code", exc?.course_code)),
    field("Section", textInput("ex-section", exc?.section)),
    field("What", actionSelect),
    field("Day", daySelect("ex-day", exc?.day || "", { allowBlank: true })),
    field("Starts", textInput("ex-start", exc?.start || "", { type: "time" })),
    field("Ends", textInput("ex-end", exc?.end || "", { type: "time" })),
    staffRow,
    field("Note", textInput("ex-note", exc?.note)),
    el("p", { class: "hint" },
      "A change alters one week; leave a field blank to keep what the timetable ",
      "says. A cancelled class stays visible, struck through. An added class has ",
      "no timetable row behind it, so it needs a day, both times and somebody to ",
      "teach it."),
  ];

  openEditor(exc ? `Week ${exc.week}, ${exc.course_code} ${exc.section}` : "An exception",
    fields,
    () => {
      const action = val("ex-action");
      const body = {
        week: Number(val("ex-week")), course_code: val("ex-code"),
        section: val("ex-section"), action,
        day: orNull("ex-day"), start: orNull("ex-start"), end: orNull("ex-end"),
        staff_id: action === "Add" ? orNull("ex-staff") : null,
        note: val("ex-note"),
      };
      if (!body.week || !body.course_code || !body.section) {
        throw new Error("A week, course code and section are needed.");
      }
      return exc
        ? api("PUT", `/api/exceptions/${exc.id}`, body)
        : api("POST", "/api/exceptions", body);
    },
    exc ? () => api("DELETE", `/api/exceptions/${exc.id}`) : null);

  setTimeout(showStaff, 0);
}

function editStaff(person) {
  const fields = [
    field("Name", textInput("st-name", person?.name, { placeholder: "Surname, First" })),
    field("Id", textInput("st-id", person?.id, { placeholder: "surname" })),
    field("Email", textInput("st-email", person?.email, { type: "email" })),
    field("Target hours a week", textInput("st-target",
      person?.target_minutes ? person.target_minutes / 60 : "",
      { type: "number", placeholder: "optional" })),
    el("p", { class: "hint" },
      "The id is what the records use. Changing it carries their staffing with it."),
  ];

  openEditor(person ? person.name : "Somebody new", fields,
    () => {
      const targetHours = val("st-target");
      const body = {
        id: val("st-id"), name: val("st-name"), email: val("st-email"),
        target_minutes: targetHours ? Math.round(Number(targetHours) * 60) : null,
      };
      if (!body.id || !body.name) throw new Error("A name and an id are needed.");
      return person
        ? api("PUT", `/api/staff/${person.id}`, body)
        : api("POST", "/api/staff", body);
    },
    person ? () => api("DELETE", `/api/staff/${person.id}`) : null);
}

// ------------------------------------------------------------ routing

const VIEWS = {
  dashboard: dashboardView,
  planner: plannerView,
  staff: staffView,
  load: loadView,
  exceptions: exceptionsView,
  setup: setupView,
};

let current = "dashboard";

function go(view) {
  if (!VIEWS[view]) return;
  if (current !== view) {
    current = view;
    openRow = null;
    assignScope = null;
    candidates = null;
  }
  location.hash = view;
  render();
}

function render() {
  if (!state) return;
  for (const button of document.querySelectorAll("#tabs button")) {
    const on = button.dataset.view === current;
    button.toggleAttribute("aria-current", on);
    if (on) button.setAttribute("aria-current", "true");
  }
  main().replaceChildren(VIEWS[current]());
}

window.addEventListener("hashchange", () => {
  const view = location.hash.slice(1);
  if (VIEWS[view] && view !== current) { current = view; render(); }
});

for (const button of document.querySelectorAll("#tabs button")) {
  button.addEventListener("click", () => go(button.dataset.view));
}

const initial = location.hash.slice(1);
if (VIEWS[initial]) current = initial;

refresh().catch((error) => {
  main().replaceChildren(el("div", { class: "issues" },
    el("strong", { text: "Could not reach the server. " }),
    "Is python app.py still running? ",
    el("span", { class: "muted", text: error.message })));
});
