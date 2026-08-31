"use strict";

// Must match VERSION in app.py. See the note there.
const APP_VERSION = "2026-08-31.3";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
              "Saturday", "Sunday"];

const DAY_VAR = {
  Monday: "--mon", Tuesday: "--tue", Wednesday: "--wed", Thursday: "--thu",
  Friday: "--fri", Saturday: "--sat", Sunday: "--sun",
};

const dayColour = (day) => `var(${DAY_VAR[day] || "--quiet"})`;

function dayDot(day) {
  return el("span", {
    class: "dot",
    style: `background:${dayColour(day)}`,
    title: day || "",
  });
}

function dayKey() {
  return el("div", { class: "daykey" },
    DAYS.slice(0, 5).map((d) =>
      el("span", {}, dayDot(d), d)));
}

let state = null;
let view = "staff";
let chosenStaff = null;

const $ = (sel) => document.querySelector(sel);
const main = () => $("#main");

// ------------------------------------------------------------ small helpers

function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

function toast(message, isError = false) {
  document.querySelectorAll(".toast").forEach((t) => t.remove());
  const node = el("div", { class: "toast" + (isError ? " error" : "") }, message);
  document.body.append(node);
  setTimeout(() => node.remove(), isError ? 6000 : 2500);
}

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    if (res.status === 404 && path.startsWith("/api/")) {
      throw new Error(
        "The running server does not have this feature. Stop it with Ctrl+C "
        + "and run python app.py again.");
    }
    let detail = `${method} ${path} failed`;
    try {
      const data = await res.json();
      if (data.detail) {
        detail = typeof data.detail === "string"
          ? data.detail
          : "Some fields are missing or the wrong shape.";
      }
    } catch (_) { /* keep the fallback */ }
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

const staffName = (id) => {
  const person = state.staff.find((s) => s.id === id);
  return person ? person.name : (id || "Unassigned");
};

const weekNumbers = () => state.weeks.map((w) => w.number);

const shortDate = (iso) =>
  new Date(iso + "T00:00:00").toLocaleDateString("en-NZ",
    { day: "numeric", month: "short" });

const hours = (mins) => (mins / 60).toFixed(1).replace(/\.0$/, "");

function ribbon(activeWeeks, { light = false } = {}) {
  const active = new Set(activeWeeks);
  return el("div", { class: "ribbon" },
    weekNumbers().map((n) =>
      el("i", {
        class: active.has(n) ? (light ? "lite" : "on") : "",
        title: `Week ${n}`,
      }, active.has(n) ? "" : "")));
}

function ribbonScale() {
  return el("div", { class: "ribbon-scale" },
    weekNumbers().map((n) => el("span", {}, n)));
}

// ------------------------------------------------------------ loading

async function refresh() {
  state = await api("GET", "/api/state");
  if (!chosenStaff || !state.staff.some((s) => s.id === chosenStaff)) {
    chosenStaff = state.staff.length ? state.staff[0].id : null;
  }
  renderChrome();
  render();
}

function staleServerBanner() {
  if (state.version === APP_VERSION) return null;
  return el("section", { class: "panel stale" },
    el("h3", {}, "The server needs restarting"),
    el("p", { class: "hint" },
      "This page has been updated but the running server has not. Stop it in "
      + "the terminal with Ctrl+C, run python app.py again, then reload. "
      + `Page ${APP_VERSION}, server ${state.version || "older than 2026-08-31.3"}.`));
}

function renderChrome() {
  const weeks = state.weeks;
  $("#term").textContent = weeks.length
    ? `${weeks.length} teaching weeks, from ${shortDate(weeks[0].starts)}`
    : "No teaching calendar yet";

  const verdict = $("#verdict");
  const count = state.problems.length;
  verdict.className = "verdict " + (count ? "bad" : "good");
  verdict.textContent = count === 0
    ? "No clashes"
    : count === 1 ? "1 clash" : `${count} clashes`;
  verdict.onclick = count
    ? () => { view = "timetable"; focusedClash = null; render(); }
    : null;
}

// ------------------------------------------------------------ staff view

function staffView() {
  if (!state.staff.length) {
    return [emptyPanel("No staff yet.", "Add people in Setup, then build the timetable.")];
  }

  const classes = state.classes.filter(
    (c) => c.staff_id === chosenStaff && c.status !== "Cancelled");
  const cancelled = state.classes.filter(
    (c) => c.status === "Cancelled" && cancelledBelongsTo(c, chosenStaff));

  const totalMins = classes.reduce((sum, c) => sum + c.minutes, 0);
  const clashWeeks = new Set(classes.filter((c) => c.clashing).map((c) => c.week));

  const picker = el("div", { class: "picker" },
    el("div", {},
      el("label", { for: "who" }, "Staff member"),
      el("select", {
        id: "who",
        onchange: (e) => { chosenStaff = e.target.value; render(); },
      }, state.staff.map((s) =>
        el("option", { value: s.id, selected: s.id === chosenStaff },
          `${s.name} (${s.id})`)))),
    el("div", {},
      el("label", {}, "Teaching hours"),
      el("div", { class: "stat" }, hours(totalMins))),
    el("div", {},
      el("label", {}, "Weeks with a clash"),
      el("div", { class: "stat" + (clashWeeks.size ? " bad" : "") },
        clashWeeks.size)),
    el("div", { style: "flex:1 1 12rem; min-width:10rem" },
      el("label", {}, "Clash weeks"),
      ribbonScale(),
      ribbon([...clashWeeks])));

  const rows = state.weeks.map((w) => {
    const mine = classes.filter((c) => c.week === w.number);
    const gone = cancelled.filter((c) => c.week === w.number);
    const cells = mine.length || gone.length
      ? el("div", { class: "cells" },
          mine.map(classCard),
          gone.map((c) => classCard(c)))
      : el("div", { class: "cells" }, "No teaching this week");

    return el("div", { class: "weekrow" + (mine.length ? "" : " free") },
      el("div", { class: "wk" }, `Wk ${w.number}`),
      el("div", { class: "dt" }, shortDate(w.starts)),
      cells);
  });

  return [
    el("section", { class: "panel" }, picker),
    el("section", { class: "panel" },
      el("h2", {}, `${staffName(chosenStaff)} across the semester`),
      el("p", { class: "hint" },
        "Red means this person is timetabled twice at once that week. "
        + "Teaching outside these courses is not shown, so a quiet week is not "
        + "necessarily a free one."),
      el("div", { class: "daykey", style: "margin-top:0.5rem" },
        DAYS.slice(0, 5).map((d) => el("span", {}, dayDot(d), d))),
      el("div", { style: "margin-top:0.6rem" }, rows)),
  ];
}

function cancelledBelongsTo(cancelledClass, staffId) {
  // A cancelled class has no staff, so trace it back through the timetable.
  return state.timetable.some(
    (r) => r.course_code === cancelledClass.course_code
      && r.section === cancelledClass.section
      && r.staff_id === staffId
      && r.weeks.includes(cancelledClass.week));
}

function classCard(c) {
  const cls = ["klass", c.status.toLowerCase(), c.clashing ? "clashing" : ""]
    .filter(Boolean).join(" ");
  return el("div", {
    class: cls,
    style: c.day ? `border-left-color:${dayColour(c.day)}` : "",
  },
    el("div", { class: "code" }, c.label),
    el("div", { class: "when" },
      c.status === "Cancelled"
        ? "Not running"
        : `${c.day.slice(0, 3)} ${c.start} to ${c.end}`),
    c.status !== "Scheduled" && el("div", { class: "note" }, c.status));
}

// ------------------------------------------------------------ clashes

function weekRanges(weeks) {
  // "1 to 4, 6 to 12" reads better than a list, and unlike "every week" it
  // stays true when one week is clear.
  const runs = [];
  for (const n of weeks) {
    const last = runs[runs.length - 1];
    if (last && n === last[1] + 1) last[1] = n;
    else runs.push([n, n]);
  }
  const text = runs
    .map(([a, b]) => (a === b ? `${a}` : `${a} to ${b}`))
    .join(", ");
  return (weeks.length === 1 ? "Week " : "Weeks ") + text;
}

// ------------------------------------------------------------ loading

async function refresh() {
  state = await api("GET", "/api/state");
  if (!chosenStaff || !state.staff.some((s) => s.id === chosenStaff)) {
    chosenStaff = state.staff.length ? state.staff[0].id : null;
  }
  renderChrome();
  render();
}

function staleServerBanner() {
  if (state.version === APP_VERSION) return null;
  return el("section", { class: "panel stale" },
    el("h3", {}, "The server needs restarting"),
    el("p", { class: "hint" },
      "This page has been updated but the running server has not. Stop it in "
      + "the terminal with Ctrl+C, run python app.py again, then reload. "
      + `Page ${APP_VERSION}, server ${state.version || "older than 2026-08-31.3"}.`));
}

function renderChrome() {
  const weeks = state.weeks;
  $("#term").textContent = weeks.length
    ? `${weeks.length} teaching weeks, from ${shortDate(weeks[0].starts)}`
    : "No teaching calendar yet";

  const verdict = $("#verdict");
  const count = state.problems.length;
  verdict.className = "verdict " + (count ? "bad" : "good");
  verdict.textContent = count === 0
    ? "No clashes"
    : count === 1 ? "1 clash" : `${count} clashes`;
  verdict.onclick = count
    ? () => { view = "timetable"; focusedClash = null; render(); }
    : null;
}

// ------------------------------------------------------------ staff view

function staffView() {
  if (!state.staff.length) {
    return [emptyPanel("No staff yet.", "Add people in Setup, then build the timetable.")];
  }

  const classes = state.classes.filter(
    (c) => c.staff_id === chosenStaff && c.status !== "Cancelled");
  const cancelled = state.classes.filter(
    (c) => c.status === "Cancelled" && cancelledBelongsTo(c, chosenStaff));

  const totalMins = classes.reduce((sum, c) => sum + c.minutes, 0);
  const clashWeeks = new Set(classes.filter((c) => c.clashing).map((c) => c.week));

  const picker = el("div", { class: "picker" },
    el("div", {},
      el("label", { for: "who" }, "Staff member"),
      el("select", {
        id: "who",
        onchange: (e) => { chosenStaff = e.target.value; render(); },
      }, state.staff.map((s) =>
        el("option", { value: s.id, selected: s.id === chosenStaff },
          `${s.name} (${s.id})`)))),
    el("div", {},
      el("label", {}, "Teaching hours"),
      el("div", { class: "stat" }, hours(totalMins))),
    el("div", {},
      el("label", {}, "Weeks with a clash"),
      el("div", { class: "stat" + (clashWeeks.size ? " bad" : "") },
        clashWeeks.size)),
    el("div", { style: "flex:1 1 12rem; min-width:10rem" },
      el("label", {}, "Clash weeks"),
      ribbonScale(),
      ribbon([...clashWeeks])));

  const rows = state.weeks.map((w) => {
    const mine = classes.filter((c) => c.week === w.number);
    const gone = cancelled.filter((c) => c.week === w.number);
    const cells = mine.length || gone.length
      ? el("div", { class: "cells" },
          mine.map(classCard),
          gone.map((c) => classCard(c)))
      : el("div", { class: "cells" }, "No teaching this week");

    return el("div", { class: "weekrow" + (mine.length ? "" : " free") },
      el("div", { class: "wk" }, `Wk ${w.number}`),
      el("div", { class: "dt" }, shortDate(w.starts)),
      cells);
  });

  return [
    el("section", { class: "panel" }, picker),
    el("section", { class: "panel" },
      el("h2", {}, `${staffName(chosenStaff)} across the semester`),
      el("p", { class: "hint" },
        "Red means this person is timetabled twice at once that week. "
        + "Teaching outside these courses is not shown, so a quiet week is not "
        + "necessarily a free one."),
      el("div", { class: "daykey", style: "margin-top:0.5rem" },
        DAYS.slice(0, 5).map((d) => el("span", {}, dayDot(d), d))),
      el("div", { style: "margin-top:0.6rem" }, rows)),
  ];
}

function cancelledBelongsTo(cancelledClass, staffId) {
  // A cancelled class has no staff, so trace it back through the timetable.
  return state.timetable.some(
    (r) => r.course_code === cancelledClass.course_code
      && r.section === cancelledClass.section
      && r.staff_id === staffId
      && r.weeks.includes(cancelledClass.week));
}

function classCard(c) {
  const cls = ["klass", c.status.toLowerCase(), c.clashing ? "clashing" : ""]
    .filter(Boolean).join(" ");
  return el("div", {
    class: cls,
    style: c.day ? `border-left-color:${dayColour(c.day)}` : "",
  },
    el("div", { class: "code" }, c.label),
    el("div", { class: "when" },
      c.status === "Cancelled"
        ? "Not running"
        : `${c.day.slice(0, 3)} ${c.start} to ${c.end}`),
    c.status !== "Scheduled" && el("div", { class: "note" }, c.status));
}

// ------------------------------------------------------------ clashes

function weekRanges(weeks) {
  // "1 to 4, 6 to 12" reads better than a list, and unlike "every week" it
  // stays true when one week is clear.
  const runs = [];
  for (const n of weeks) {
    const last = runs[runs.length - 1];
    if (last && n === last[1] + 1) last[1] = n;
    else runs.push([n, n]);
  }
  const text = runs
    .map(([a, b]) => (a === b ? `${a}` : `${a} to ${b}`))
    .join(", ");
  return (weeks.length === 1 ? "Week " : "Weeks ") + text;
}

function clashesView() {
  if (!state.problems.length) {
    return [emptyPanel("No clashes.",
      "Nobody in the staff list is timetabled twice at once.")];
  }

  const rows = state.problems.flatMap((p, i) => {
    const row = el("tr", { class: openResolve === i ? "resolving" : "" },
      el("td", {}, el("div", {}, staffName(p.staff_id)),
        el("div", { class: "muted" }, p.staff_id)),
      el("td", {},
        el("div", {}, p.a.label),
        el("div", { class: "muted" },
          dayDot(p.a.day), `${p.a.day.slice(0, 3)} ${p.a.start} to ${p.a.end}`)),
      el("td", {},
        el("div", {}, p.b.label),
        el("div", { class: "muted" },
          dayDot(p.b.day), `${p.b.day.slice(0, 3)} ${p.b.start} to ${p.b.end}`)),
      el("td", { class: "mid tight" }, p.weeks.length),
      el("td", { style: "min-width:10rem" }, ribbonScale(), ribbon(p.weeks)),
      el("td", { class: "tight" }, weekRanges(p.weeks)),
      el("td", { class: "tight" },
        el("button", {
          class: "link",
          onclick: async () => {
            if (openResolve === i) { openResolve = null; return render(); }
            openResolve = i;
            render();
            const panel = await resolveRow(p, i);
            const target = document.querySelector("tr.resolving");
            if (target && openResolve === i) target.after(panel);
          },
        }, openResolve === i ? "Close" : "Resolve")));

    return [row];
  });

  return [
    el("section", { class: "panel" },
      el("h2", {}, "What does not work"),
      el("p", { class: "hint" },
        "One row per clash, however many weeks it happens in. Resolve shows who "
        + "is actually free at that time, so handing a class over cannot create "
        + "a new clash by accident."),
      el("div", { class: "scroll", style: "margin-top:0.7rem" },
        el("table", {},
          el("thead", {}, el("tr", {},
            el("th", {}, "Staff"),
            el("th", {}, "This class"),
            el("th", {}, "Collides with"),
            el("th", { class: "mid" }, "Weeks"),
            el("th", {}, "When"),
            el("th", {}, "Shape"),
            el("th", {}))),
          el("tbody", {}, rows)))),
  ];
}

// ------------------------------------------------------------ load

function loadView() {
  if (!state.staff.length) return [emptyPanel("No staff yet.", "Add people in Setup.")];

  const clashCells = new Set(
    state.classes.filter((c) => c.clashing).map((c) => `${c.staff_id}|${c.week}`));

  const body = state.staff.map((s) => {
    const perWeek = state.load[s.id] || {};
    const total = Object.values(perWeek).reduce((a, b) => a + b, 0);
    return el("tr", {},
      el("td", {}, s.name),
      el("td", { class: "muted tight" }, s.id),
      state.weeks.map((w) => {
        const mins = perWeek[w.number] || 0;
        const bad = clashCells.has(`${s.id}|${w.number}`);
        return el("td", {
          class: "mid tight",
          style: bad
            ? "background:var(--clash-wash);color:var(--clash);font-weight:600"
            : (mins ? "" : "color:var(--quiet)"),
          title: bad ? `Clash in week ${w.number}` : "",
        }, mins ? hours(mins) : ".");
      }),
      el("td", { class: "num tight" }, hours(total)));
  });

  const totals = state.weeks.map((w) => {
    const sum = state.staff.reduce(
      (acc, s) => acc + ((state.load[s.id] || {})[w.number] || 0), 0);
    return el("td", { class: "mid tight" }, sum ? hours(sum) : "");
  });

  return [
    el("section", { class: "panel" },
      el("h2", {}, "Teaching hours by week"),
      el("p", { class: "hint" },
        "Timetabled contact hours only. Cancelled classes count as zero, and "
        + "supervision, marking and admin are not included."),
      el("div", { class: "scroll", style: "margin-top:0.7rem" },
        el("table", {},
          el("thead", {}, el("tr", {},
            el("th", {}, "Staff"),
            el("th", {}, "ID"),
            state.weeks.map((w) => el("th", { class: "mid" }, w.number)),
            el("th", { class: "num" }, "Total"))),
          el("tbody", {}, body),
          el("tfoot", {}, el("tr", {},
            el("th", {}, "All staff"),
            el("th", {}),
            totals,
            el("th", { class: "num" },
              hours(state.classes.reduce((a, c) => a + c.minutes, 0)))))))),
  ];
}

// ------------------------------------------------------------ timetable

// ----------------------------------------------- timetable, clashes and fixes

// Which clash panel is open, and the availability lists it needs. Held as
// state and drawn during the normal render, so nothing depends on splicing a
// panel into the page after the fact.
let resolving = null;      // { index, a: [...], b: [...] }
let focusedClash = null;   // index of the pair being singled out

const sameClass = (cls, row) =>
  cls.course_code === row.course_code && cls.section === row.section;

function clashesForRow(row) {
  // A row can be caught in more than one clash, and a section split across two
  // rows only belongs to the clashes that fall in its own weeks.
  return state.problems
    .map((p, i) => ({ p, i }))
    .filter(({ p }) =>
      [p.a, p.b].some((c) =>
        sameClass(c, row) && p.weeks.some((w) => row.weeks.includes(w))))
    .map(({ i }) => i);
}

function clashBadge(index, { small = false } = {}) {
  return el("button", {
    class: "badge" + (focusedClash === index ? " focused" : "") + (small ? " sm" : ""),
    title: `Clash ${index + 1}. Click to single it out.`,
    onclick: () => {
      focusedClash = focusedClash === index ? null : index;
      render();
    },
  }, index + 1);
}

async function openResolve(problem, index) {
  const ask = (c) => api("POST", "/api/availability", {
    day: c.day, start: c.start, end: c.end, weeks: problem.weeks,
    course_code: c.course_code, section: c.section,
  });
  try {
    const [a, b] = await Promise.all([ask(problem.a), ask(problem.b)]);
    resolving = { index, a: a.staff, b: b.staff };
    focusedClash = index;
    render();
  } catch (err) {
    toast(err.message, true);
  }
}

function candidateList(problem, c, people, side) {
  // Whoever could actually take it comes first, least loaded at the top. An
  // alphabetical list buries the only useful answers at the bottom.
  const sorted = [...people].sort((x, y) =>
    (y.free - x.free) || (x.minutes - y.minutes) || x.name.localeCompare(y.name));
  const name = `cand-${side}`;
  const scopeName = `scope-${side}`;

  return el("div", { class: "side" },
    el("h4", {}, "Hand over ", c.label),
    el("div", { class: "when" }, dayDot(c.day), `${c.day} ${c.start} to ${c.end}`),
    el("div", { class: "candidates" },
      sorted.map((s) =>
        el("label", {
          class: "cand" + (s.free ? "" : " busy")
            + (s.id === problem.staff_id ? " current" : ""),
        },
          el("input", { type: "radio", name, value: s.id, disabled: !s.free }),
          el("span", { class: "who" }, s.name),
          s.free
            ? el("span", { class: "hrs" }, `${hours(s.minutes)} hrs`)
            : el("span", { class: "why" },
                `busy ${weekRanges(s.busy_weeks).toLowerCase()}`)))),
    el("div", { class: "scope" },
      el("label", {},
        el("input", { type: "radio", name: scopeName, value: "all", checked: true }),
        "Every week it runs"),
      el("label", {},
        el("input", { type: "radio", name: scopeName, value: "clashing" }),
        `Only ${weekRanges(problem.weeks).toLowerCase()}, splitting the row`)),
    el("p", { class: "hint", style: "margin:0.35rem 0 0" },
      "Either way this changes the timetable. Splitting leaves the original row "
      + "with the weeks it still covers and adds a second row for the rest, so "
      + "who teaches when stays visible in the table below."),
    el("div", { class: "toolbar", style: "margin:0.7rem 0 0" },
      el("button", {
        class: "action primary",
        onclick: async () => {
          const picked = document.querySelector(`input[name="${name}"]:checked`);
          if (!picked) return toast("Choose someone who is free.", true);
          const scope = document.querySelector(
            `input[name="${scopeName}"]:checked`).value;
          try {
            const res = await api("POST", "/api/reassign", {
              course_code: c.course_code,
              section: c.section,
              staff_id: picked.value,
              weeks: scope === "all" ? null : problem.weeks,
            });
            resolving = null;
            focusedClash = null;
            await refresh();
            toast(res.split
              ? `${c.label} split, ${staffName(picked.value)} takes `
                + weekRanges(problem.weeks).toLowerCase()
              : `${c.label} handed to ${staffName(picked.value)}`);
          } catch (err) { toast(err.message, true); }
        },
      }, "Hand it over")));
}

function clashPanel() {
  if (!state.problems.length) {
    return el("section", { class: "panel ok" },
      el("h2", {}, "Nothing clashes"),
      el("p", { class: "hint" },
        "Nobody in the staff list is timetabled twice at once. Teaching outside "
        + "these courses is not tracked, so this is not a statement about "
        + "anyone's overall availability."));
  }

  const rows = state.problems.flatMap((p, i) => {
    const open = resolving && resolving.index === i;
    const row = el("div", {
      class: "clash" + (focusedClash === i ? " focused" : "")
        + (focusedClash !== null && focusedClash !== i ? " dimmed" : ""),
    },
      clashBadge(i),
      el("div", { class: "pair" },
        el("div", { class: "who" }, staffName(p.staff_id)),
        el("div", { class: "vs" },
          dayDot(p.a.day), el("b", {}, p.a.label), ` ${p.a.start} to ${p.a.end}`,
          el("span", { class: "muted" }, "  against  "),
          dayDot(p.b.day), el("b", {}, p.b.label), ` ${p.b.start} to ${p.b.end}`)),
      el("div", { class: "when" }, ribbonScale(), ribbon(p.weeks)),
      el("div", { class: "weeks" }, weekRanges(p.weeks)),
      el("button", {
        class: "action",
        onclick: () => {
          if (open) { resolving = null; return render(); }
          openResolve(p, i);
        },
      }, open ? "Close" : "Fix this"));

    if (!open) return [row];
    return [row, el("div", { class: "resolve" },
      el("div", { class: "sides" },
        candidateList(p, p.a, resolving.a, "a"),
        candidateList(p, p.b, resolving.b, "b")))];
  });

  return el("section", { class: "panel" },
    el("h2", {}, state.problems.length === 1
      ? "One clash to sort out"
      : `${state.problems.length} clashes to sort out`),
    el("p", { class: "hint" },
      "Each clash has a number, and both halves of the pair carry it in the "
      + "table below. Click a number to single that pair out. Fix this shows "
      + "who is free at that time, so handing a class over cannot create a new "
      + "clash by accident."),
    el("div", { class: "clashlist" }, rows));
}

function timetableView() {
  const rows = state.timetable.map((r) => {
    const mine = clashesForRow(r);
    const dimmed = focusedClash !== null && !mine.includes(focusedClash);
    return el("tr", {
      class: (mine.length ? "hasclash " : "")
        + (dimmed ? "dimmed" : "")
        + (focusedClash !== null && mine.includes(focusedClash) ? " focused" : ""),
    },
      el("td", { class: "mid tight" },
        mine.length
          ? el("span", { class: "badges" }, mine.map((i) => clashBadge(i, { small: true })))
          : el("span", { class: "muted" }, "")),
      el("td", {}, el("div", {}, r.course_code),
        el("div", { class: "muted" }, r.course_title)),
      el("td", {}, r.section),
      el("td", {}, staffName(r.staff_id)),
      el("td", { class: "tight" },
        dayDot(r.day), `${r.day.slice(0, 3)} ${r.start} to ${r.end}`),
      el("td", { style: "min-width:9rem" }, ribbonScale(), ribbon(r.weeks, { light: true })),
      el("td", { class: "tight" },
        el("button", { class: "link", onclick: () => editTimetable(r) }, "Edit")));
  });

  return [
    issuesPanel(),
    clashPanel(),
    el("section", { class: "panel" },
      el("div", { class: "toolbar" },
        el("h2", {}, "The timetable as issued"),
        el("span", { class: "spacer" }),
        focusedClash !== null
          ? el("button", {
              class: "action",
              onclick: () => { focusedClash = null; render(); },
            }, "Show everything")
          : null,
        el("button", { class: "action primary", onclick: () => editTimetable(null) },
          "Add a class")),
      el("p", { class: "hint" },
        "One row per course and section, with the weeks it runs. If a section "
        + "changes lecturer partway through the semester, add a second row for "
        + "the later weeks rather than using exceptions. Handing part of a "
      + "semester to someone else does that splitting for you."),
      rows.length
        ? el("div", { class: "scroll", style: "margin-top:0.7rem" },
            el("table", {},
              el("thead", {}, el("tr", {},
                el("th", { class: "mid" }, "Clash"),
                el("th", {}, "Course"),
                el("th", {}, "Section"),
                el("th", {}, "Staff"),
                el("th", {}, "When"),
                el("th", {}, "Weeks"),
                el("th", {}))),
              el("tbody", {}, rows)))
        : el("p", { class: "empty" }, "Nothing here yet. Add your first class.")),
  ];
}

// ------------------------------------------------------------ exceptions

function exceptionsView() {
  const rows = state.exceptions.map((x) =>
    el("tr", {},
      el("td", { class: "mid tight" }, x.week),
      el("td", {}, `${x.course_code} ${x.section}`),
      el("td", {}, x.action),
      el("td", {}, x.staff_id ? staffName(x.staff_id) : el("span", { class: "muted" }, "unchanged")),
      el("td", { class: "tight" },
        x.action === "Cancel"
          ? el("span", { class: "muted" }, "not running")
          : describeOverride(x)),
      el("td", { class: "muted" }, x.note),
      el("td", { class: "tight" },
        el("button", { class: "link", onclick: () => editException(x) }, "Edit"))));

  return [
    issuesPanel(),
    el("section", { class: "panel" },
      el("div", { class: "toolbar" },
        el("h2", {}, "Weeks that depart from the timetable"),
        el("span", { class: "spacer" }),
        el("button", { class: "action primary", onclick: () => editException(null) },
          "Add an exception")),
      el("p", { class: "hint" },
        "For weeks that genuinely depart from the timetable. Not for staffing: "
        + "if someone else is teaching, change the timetable so the table says "
        + "so. Change alters one week and leaves everything you do not fill in "
        + "as it was. Cancel means the class does not run. Add creates an extra "
        + "class, so it needs every field."),
      rows.length
        ? el("div", { class: "scroll", style: "margin-top:0.7rem" },
            el("table", {},
              el("thead", {}, el("tr", {},
                el("th", { class: "mid" }, "Week"),
                el("th", {}, "Class"),
                el("th", {}, "Action"),
                el("th", {}, "Staff"),
                el("th", {}, "Time"),
                el("th", {}, "Note"),
                el("th", {}))),
              el("tbody", {}, rows)))
        : el("p", { class: "empty" },
            "No exceptions. Every class runs exactly as timetabled.")),
  ];
}

function describeOverride(x) {
  const bits = [];
  if (x.day) bits.push(x.day.slice(0, 3));
  if (x.start && x.end) bits.push(`${x.start} to ${x.end}`);
  else if (x.start) bits.push(`starts ${x.start}`);
  else if (x.end) bits.push(`ends ${x.end}`);
  return bits.length ? bits.join(" ") : el("span", { class: "muted" }, "unchanged");
}

// ------------------------------------------------------------ setup

function setupView() {
  const staffRows = state.staff.map((s) =>
    el("tr", {},
      el("td", {}, s.id),
      el("td", {}, s.name),
      el("td", { class: "muted" }, s.email),
      el("td", { class: "tight" },
        el("button", { class: "link", onclick: () => editStaff(s) }, "Edit"))));

  const weekRows = state.weeks.map((w) =>
    el("tr", {},
      el("td", { class: "mid tight" }, w.number),
      el("td", { class: "tight" },
        el("input", {
          type: "date", value: w.starts,
          onchange: (e) => saveWeek(w.number, "starts", e.target.value),
        })),
      el("td", { class: "muted tight" }, shortDate(w.ends)),
      el("td", {},
        el("input", {
          type: "text", value: w.note, style: "width:100%",
          placeholder: "e.g. mid semester break follows",
          onchange: (e) => saveWeek(w.number, "note", e.target.value),
        }))));

  return [
    issuesPanel(),
    el("section", { class: "panel" },
      el("div", { class: "toolbar" },
        el("h2", {}, "Staff you are responsible for"),
        el("span", { class: "spacer" }),
        el("button", { class: "action primary", onclick: () => editStaff(null) },
          "Add a person")),
      staffRows.length
        ? el("table", {},
            el("thead", {}, el("tr", {},
              el("th", {}, "ID"), el("th", {}, "Name"),
              el("th", {}, "Email"), el("th", {}))),
            el("tbody", {}, staffRows))
        : el("p", { class: "empty" }, "No staff yet.")),

    el("section", { class: "panel" },
      el("div", { class: "toolbar" },
        el("h2", {}, "Teaching calendar"),
        el("span", { class: "spacer" }),
        el("button", { class: "action", onclick: addWeek }, "Add a week"),
        state.weeks.length
          ? el("button", { class: "action", onclick: removeLastWeek }, "Remove last week")
          : null),
      el("p", { class: "hint" },
        "Week numbers run consecutively through teaching. Breaks are gaps "
        + "between dates, not extra weeks. Set the Monday and the rest of the "
        + "week follows."),
      state.weeks.length
        ? el("table", { style: "margin-top:0.6rem" },
            el("thead", {}, el("tr", {},
              el("th", { class: "mid" }, "Week"), el("th", {}, "Monday"),
              el("th", {}, "Sunday"), el("th", {}, "Note"))),
            el("tbody", {}, weekRows))
        : el("p", { class: "empty" }, "No teaching calendar yet.")),

    el("section", { class: "panel" },
      el("h2", {}, "Sample data"),
      el("p", { class: "hint" },
        "The tool starts with two example courses that exercise every rule: a "
        + "lecture running in three weeks only, workshops shortened in those "
        + "weeks, a public holiday cancellation, a one week guest lecturer and "
        + "an added crit session."),
      el("div", { class: "toolbar", style: "margin-top:0.7rem" },
        el("button", {
          class: "action",
          onclick: () => confirmThen(
            "Replace everything with the sample data?",
            () => api("POST", "/api/sample-data"), "Sample data loaded"),
        }, "Reload sample data"),
        el("button", {
          class: "action",
          onclick: () => confirmThen(
            "Delete all staff, weeks, timetable rows and exceptions?",
            () => api("DELETE", "/api/all-data"), "Everything cleared"),
        }, "Clear everything"))),
  ];
}

async function confirmThen(question, action, done) {
  if (!confirm(question)) return;
  try {
    await action();
    await refresh();
    toast(done);
  } catch (err) {
    toast(err.message, true);
  }
}

const sixDaysOn = (iso) =>
  new Date(new Date(iso + "T00:00:00").getTime() + 6 * 86400000)
    .toISOString().slice(0, 10);

async function saveWeek(number, field, value) {
  const weeks = state.weeks.map((w) => {
    if (w.number !== number) return { ...w };
    const next = { ...w, [field]: value };
    if (field === "starts") next.ends = sixDaysOn(value);
    return next;
  });
  try {
    await api("PUT", "/api/weeks", { weeks });
    await refresh();
  } catch (err) {
    toast(err.message, true);
  }
}

async function addWeek() {
  const last = state.weeks[state.weeks.length - 1];
  const next = last
    ? new Date(new Date(last.starts + "T00:00:00").getTime() + 7 * 86400000)
    : new Date();
  const iso = next.toISOString().slice(0, 10);
  const weeks = [...state.weeks.map((w) => ({ ...w })),
    { number: (last ? last.number : 0) + 1, starts: iso,
      ends: sixDaysOn(iso), note: "" }];
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
  return el("section", { class: "panel issues" },
    el("h3", {}, state.issues.length === 1
      ? "One thing needs attention in the data"
      : `${state.issues.length} things need attention in the data`),
    el("p", { class: "hint" },
      "These are problems with the records themselves, not with the timetable. "
      + "Clash detection may be wrong until they are fixed."),
    el("ul", {}, state.issues.map((i) => el("li", {}, i))));
}

function emptyPanel(heading, hint) {
  return el("section", { class: "panel" },
    el("h2", {}, heading),
    el("p", { class: "hint" }, hint));
}

// ------------------------------------------------------------ editor dialog

let saveHandler = null;

function openEditor(title, fields, onSave, onDelete) {
  $("#editor-title").textContent = title;
  const body = $("#editor-body");
  body.replaceChildren(...fields);
  saveHandler = onSave;
  const del = $("#editor-delete");
  del.hidden = !onDelete;
  del.onclick = async () => {
    if (!confirm("Delete this permanently?")) return;
    try {
      await onDelete();
      $("#editor").close();
      await refresh();
      toast("Deleted");
    } catch (err) { toast(err.message, true); }
  };
  $("#editor").showModal();
}

$("#editor-cancel").onclick = () => $("#editor").close();
$("#editor-save").onclick = async () => {
  try {
    await saveHandler();
    $("#editor").close();
    await refresh();
    toast("Saved");
  } catch (err) {
    toast(err.message, true);
  }
};

function field(label, input) {
  return el("div", { class: "field" }, el("label", {}, label), input);
}

function textInput(id, value, opts = {}) {
  return el("input", { id, type: opts.type || "text", value: value ?? "",
    placeholder: opts.placeholder || "" });
}

function staffSelect(id, value, { allowBlank = false, blankLabel = "" } = {}) {
  return el("select", { id },
    allowBlank ? el("option", { value: "", selected: !value }, blankLabel) : null,
    state.staff.map((s) =>
      el("option", { value: s.id, selected: s.id === value }, `${s.name} (${s.id})`)));
}

function daySelect(id, value, { allowBlank = false } = {}) {
  return el("select", { id },
    allowBlank ? el("option", { value: "", selected: !value }, "Unchanged") : null,
    DAYS.map((d) => el("option", { value: d, selected: d === value }, d)));
}

function weekTicks(id, selected) {
  // A new class usually runs every week, so that is the starting point.
  const chosen = new Set(selected ?? state.weeks.map((w) => w.number));
  const ticks = el("div", { class: "weekticks", id },
    state.weeks.map((w) =>
      el("label", { class: chosen.has(w.number) ? "checked" : "" },
        el("input", {
          type: "checkbox", value: w.number, checked: chosen.has(w.number),
          onchange: (e) => e.target.closest("label")
            .classList.toggle("checked", e.target.checked),
        }),
        w.number)));

  const setAll = (on) => {
    ticks.querySelectorAll("input").forEach((box) => {
      box.checked = on;
      box.closest("label").classList.toggle("checked", on);
    });
  };

  return el("div", {},
    ticks,
    el("div", { class: "toolbar", style: "margin:0.4rem 0 0" },
      el("button", { class: "link", onclick: () => setAll(true) }, "Tick all"),
      el("button", { class: "link", onclick: () => setAll(false) }, "Clear")));
}

const ticked = (id) =>
  [...document.querySelectorAll(`#${id} input:checked`)].map((i) => Number(i.value));

const val = (id) => {
  const node = document.getElementById(id);
  return node ? node.value.trim() : "";
};
const orNull = (id) => val(id) || null;

// ------------------------------------------------------------ editors

function editTimetable(row) {
  const fields = [
    el("div", { class: "row" },
      field("Course code", textInput("f-code", row?.course_code, { placeholder: "111.701" })),
      field("Section", textInput("f-section", row?.section, { placeholder: "A" }))),
    field("Course title", textInput("f-title", row?.course_title)),
    field("Staff member", staffSelect("f-staff", row?.staff_id,
      { allowBlank: true, blankLabel: "Not one of our staff" })),
    el("div", { class: "row" },
      field("Day", daySelect("f-day", row?.day || "Monday")),
      field("Starts", textInput("f-start", row?.start || "09:00", { type: "time" })),
      field("Ends", textInput("f-end", row?.end || "12:00", { type: "time" }))),
    field("Weeks it runs", weekTicks("f-weeks", row?.weeks)),
  ];

  const collect = () => ({
    course_code: val("f-code"),
    course_title: val("f-title"),
    section: val("f-section"),
    staff_id: orNull("f-staff"),
    day: val("f-day"),
    start: val("f-start"),
    end: val("f-end"),
    weeks: ticked("f-weeks"),
  });

  openEditor(
    row ? `${row.course_code} ${row.section}` : "Add a class",
    fields,
    async () => {
      const body = collect();
      if (!body.course_code || !body.section) {
        throw new Error("A class needs a course code and a section.");
      }
      if (!body.weeks.length) {
        throw new Error("Tick at least one week, or the class never runs.");
      }
      if (body.end <= body.start) {
        throw new Error("The finish time must be after the start time.");
      }
      return row
        ? api("PUT", `/api/timetable/${row.id}`, body)
        : api("POST", "/api/timetable", body);
    },
    row ? () => api("DELETE", `/api/timetable/${row.id}`) : null);
}

function editException(row) {
  const sections = [...new Set(state.timetable.map(
    (r) => `${r.course_code}|${r.section}`))].sort();

  const fields = [
    el("div", { class: "row" },
      field("Week", el("select", { id: "f-week" },
        state.weeks.map((w) => el("option",
          { value: w.number, selected: w.number === row?.week },
          `Week ${w.number}`)))),
      field("Class", el("select", { id: "f-class" },
        sections.map((key) => {
          const [code, section] = key.split("|");
          const selected = row && row.course_code === code && row.section === section;
          return el("option", { value: key, selected }, `${code} ${section}`);
        }))),
      field("Action", el("select", { id: "f-action" },
        ["Change", "Cancel", "Add"].map((a) =>
          el("option", { value: a, selected: a === row?.action }, a))))),
    field("Staff member", staffSelect("f-staff", row?.staff_id,
      { allowBlank: true, blankLabel: "Unchanged" })),
    el("div", { class: "row" },
      field("Day", daySelect("f-day", row?.day, { allowBlank: true })),
      field("Starts", textInput("f-start", row?.start, { type: "time" })),
      field("Ends", textInput("f-end", row?.end, { type: "time" }))),
    field("Note", textInput("f-note", row?.note,
      { placeholder: "why this week is different" })),
    el("p", { class: "hint" },
      "Leave a field blank to keep what the timetable says. An added class has "
      + "nothing to inherit, so it needs staff, day and both times."),
  ];

  const collect = () => {
    const [code, section] = val("f-class").split("|");
    return {
      week: Number(val("f-week")),
      course_code: code,
      section,
      action: val("f-action"),
      staff_id: orNull("f-staff"),
      day: orNull("f-day"),
      start: orNull("f-start"),
      end: orNull("f-end"),
      note: val("f-note"),
    };
  };

  openEditor(
    row ? "Edit exception" : "Add an exception",
    fields,
    async () => {
      const body = collect();
      if (!body.course_code) throw new Error("Add a class to the timetable first.");
      if (body.action === "Add") {
        const missing = ["staff_id", "day", "start", "end"]
          .filter((k) => !body[k]);
        if (missing.length) {
          throw new Error("An added class needs staff, day, start and finish.");
        }
      }
      if (body.start && body.end && body.end <= body.start) {
        throw new Error("The finish time must be after the start time.");
      }
      return row
        ? api("PUT", `/api/exceptions/${row.id}`, body)
        : api("POST", "/api/exceptions", body);
    },
    row ? () => api("DELETE", `/api/exceptions/${row.id}`) : null);
}

function editStaff(person) {
  const fields = [
    el("div", { class: "row" },
      field("ID", textInput("f-id", person?.id, { placeholder: "S01" })),
      field("Name", textInput("f-name", person?.name, { placeholder: "Surname, First" }))),
    field("Email", textInput("f-email", person?.email, { type: "email" })),
  ];

  openEditor(
    person ? person.name : "Add a person",
    fields,
    async () => {
      const body = { id: val("f-id"), name: val("f-name"), email: val("f-email") };
      if (!body.id || !body.name) throw new Error("A person needs an ID and a name.");
      return person
        ? api("PUT", `/api/staff/${person.id}`, body)
        : api("POST", "/api/staff", body);
    },
    person ? () => api("DELETE", `/api/staff/${person.id}`) : null);
}

// ------------------------------------------------------------ routing

const VIEWS = {
  staff: staffView,
  load: loadView,
  timetable: timetableView,
  exceptions: exceptionsView,
  setup: setupView,
};

function render() {
  main().replaceChildren(
    ...[staleServerBanner(), ...VIEWS[view]()].filter(Boolean));
  document.querySelectorAll("#tabs button").forEach((b) => {
    b.setAttribute("aria-current", b.dataset.view === view ? "true" : "false");
  });
}

$("#tabs").addEventListener("click", (e) => {
  const button = e.target.closest("button");
  if (!button) return;
  view = button.dataset.view;
  resolving = null;
  focusedClash = null;
  render();
});

refresh().catch((err) => {
  main().replaceChildren(el("section", { class: "panel" },
    el("h2", {}, "Could not load the data"),
    el("p", { class: "hint" }, err.message)));
});
