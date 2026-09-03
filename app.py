"""Web application for the staffing tool.

Run it with:

    python app.py

then open http://127.0.0.1:8000 in a browser. The database is created and
seeded with sample data on first run.

This layer translates between HTTP and the engine. It holds no rules about how
timetables behave; those all live in engine.py. The one thing it is responsible
for is refusing a write the engine says is impossible, which is what makes the
double booking rule real rather than advisory.
"""

from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import date
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import engine
import importer
import seed
import store

HERE = Path(__file__).parent

# Bumped whenever the API changes. The browser reads app.js fresh from disk on
# every load, but the routes live in this process, so an unrestarted server
# serves a new front end against old endpoints. The front end compares this
# against its own copy and says so rather than failing with a bare 404.
VERSION = "2026-09-04.1"


def active_term(conn) -> tuple[str, str]:
    """The term whose plan every page is showing.

    Blank is a term like any other: it is what an unset tool, and anything
    migrated from before terms existed, is planning.
    """
    held = store.get_settings(conn)
    return (held.get("academic_year", ""), held.get("semester", ""))


@contextmanager
def db():
    conn = store.connect()
    try:
        yield conn
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    with db() as conn:
        store.init(conn)
        if store.is_new(conn):
            seed.load(conn)
    yield


app = FastAPI(title="Timetable staffing", lifespan=lifespan)


# ------------------------------------------------------------ request bodies

class StaffIn(BaseModel):
    id: str
    name: str
    email: str = ""
    target_minutes: int | None = None


class TimetableIn(BaseModel):
    course_code: str
    section: str
    day: str
    start: str
    end: str
    weeks: list[int] = Field(default_factory=list)


class ExceptionIn(BaseModel):
    week: int
    course_code: str
    section: str
    action: str
    day: str | None = None
    start: str | None = None
    end: str | None = None
    staff_id: str | None = None   # added classes only
    note: str = ""


class WeeksIn(BaseModel):
    weeks: list[dict]


class AvailabilityIn(BaseModel):
    day: str
    start: str
    end: str
    weeks: list[int]
    timetable_id: int | None = None


class AssignIn(BaseModel):
    timetable_id: int
    staff_id: str
    weeks: list[int] | None = None    # None means every week the class runs
    replace: bool = False             # take weeks that somebody else holds


class UnassignIn(BaseModel):
    timetable_id: int
    weeks: list[int] | None = None


class CommitIn(BaseModel):
    rows: list[dict]
    mode: str = "replace"


class CourseCommitIn(BaseModel):
    rows: list[dict]
    mode: str = "merge"          # merge | replace_offering | replace_all


class BreakIn(BaseModel):
    starts: str
    ends: str


class WeeksGenerateIn(BaseModel):
    first_monday: str
    count: int
    breaks: list[BreakIn] = Field(default_factory=list)


class SettingsIn(BaseModel):
    academic_year: str = ""
    semester: str = ""


# ------------------------------------------------------------ serialisation

def week_json(w: engine.Week) -> dict:
    return {
        "number": w.number,
        "starts": w.starts.isoformat(),
        "ends": w.ends.isoformat(),
        "note": w.note,
    }


def staff_json(s: engine.StaffMember) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "email": s.email,
        "target_minutes": s.target_minutes,
    }


def course_json(c: engine.Course) -> dict:
    return {
        "code": c.code,
        "name": c.name,
        "academic_year": c.academic_year,
        "semester": c.semester,
        "occurrence": c.occurrence,
        "college": c.college,
        "programme": c.programme,
        "coordinator": c.coordinator,
        "coordinator_email": c.coordinator_email,
        "offering_coordinator": c.offering_coordinator,
        "offering_coordinator_email": c.offering_coordinator_email,
        "grade_reviewer": c.grade_reviewer,
        "grade_reviewer_email": c.grade_reviewer_email,
        "department": c.department,
    }


def timetable_json(r: engine.TimetableRow) -> dict:
    return {
        "id": r.id,
        "course_code": r.course_code,
        "section": r.section,
        "day": r.day,
        "start": store.from_time(r.start),
        "end": store.from_time(r.end),
        "weeks": sorted(r.weeks),
    }


def exception_json(e: engine.ExceptionRow) -> dict:
    return {
        "id": e.id,
        "week": e.week,
        "course_code": e.course_code,
        "section": e.section,
        "action": e.action.value,
        "day": e.day,
        "start": store.from_time(e.start),
        "end": store.from_time(e.end),
        "staff_id": e.staff_id,
        "note": e.note,
    }


def class_json(c: engine.Class) -> dict:
    return {
        "week": c.week,
        "course_code": c.course_code,
        "course_title": c.course_title,
        "section": c.section,
        "label": c.label,
        "staff_id": c.staff_id,
        "day": c.day,
        "start": store.from_time(c.start),
        "end": store.from_time(c.end),
        "status": c.status.value,
        "minutes": c.minutes,
        "runs": c.runs,
        "covered": c.covered,
        "timetable_row_id": c.timetable_row_id,
        "exception_id": c.exception_id,
    }


def conflict_json(c: engine.Conflict) -> dict:
    return {
        "week": c.week,
        "proposed": class_json(c.proposed),
        "existing": class_json(c.existing),
    }


def shape_json(s: engine.Shape) -> dict:
    return {
        "staff_id": s.staff_id,
        "usual": [class_json(c) for c in s.usual],
        "usual_weeks": list(s.usual_weeks),
        "settled": s.is_settled,
        "minutes": s.minutes,
        "departures": [
            {
                "weeks": list(d.weeks),
                "classes": [class_json(c) for c in d.classes],
                "added": [class_json(c) for c in d.added],
                "gone": [class_json(c) for c in d.gone],
                "cancelled": [class_json(c) for c in d.cancelled],
                "moved": [
                    {"usually": class_json(a), "instead": class_json(b)}
                    for a, b in d.moved
                ],
            }
            for d in s.departures
        ],
    }


def planning_from(settings: dict) -> tuple[str, str] | None:
    year, semester = settings.get("academic_year", ""), settings.get("semester", "")
    return (year, semester) if year and semester else None


# ------------------------------------------------------------ routes

@app.get("/api/state")
def state() -> dict:
    with db() as conn:
        weeks, staff, timetable, exceptions, assignments, courses = store.load_all(conn, active_term(conn))
        settings = store.get_settings(conn)
        has_sample = store.has_sample(conn)
        known_terms = store.terms(conn)

    classes = engine.expand(timetable, exceptions, assignments, courses)
    cover = engine.coverage(classes)
    problems = engine.find_problems(classes)

    # Flag the exact classes that collide, not everything sharing their label.
    # A section can appear twice in one week (an added class alongside the
    # timetabled one), and only one of them may be the problem.
    position = {}
    for i, c in enumerate(classes):
        position.setdefault(c, i)
    clashing = set()
    for clash in engine.find_clashes(classes):
        clashing.add(position[clash.a])
        clashing.add(position[clash.b])

    grouped = engine.group_assignments(assignments)

    return {
        "version": VERSION,
        "weeks": [week_json(w) for w in weeks],
        "staff": [staff_json(s) for s in staff],
        "timetable": [timetable_json(r) for r in timetable],
        "exceptions": [exception_json(e) for e in exceptions],
        "assignments": [
            {"timetable_id": row_id, "staff_id": staff_id, "weeks": list(week_list)}
            for row_id, spans in sorted(grouped.items())
            for staff_id, week_list in spans
        ],
        "classes": [
            class_json(c) | {"id": i, "clashing": i in clashing}
            for i, c in enumerate(classes)
        ],
        "coverage": {
            "total": cover.total,
            "covered": cover.covered,
            "percent": cover.percent,
            "rows": engine.uncovered_rows(classes),
        },
        "load": engine.load_by_staff(classes),
        "over_target": [
            {"staff_id": sid, "week": week, "minutes": minutes, "target": target}
            for sid, week, minutes, target in engine.over_target(staff, classes)
        ],
        "problems": [
            {
                "staff_id": p.staff_id,
                "a": class_json(p.a),
                "b": class_json(p.b),
                "weeks": list(p.weeks),
                "structural": p.is_structural,
            }
            for p in problems
        ],
        "courses": [course_json(c) for c in courses],
        "teaching": engine.teachers_for(classes),
        "has_sample": has_sample,
        "terms": [
            {"academic_year": year, "semester": semester}
            for year, semester in known_terms
        ],
        "settings": {
            "academic_year": settings.get("academic_year", ""),
            "semester": settings.get("semester", ""),
        },
        "shapes": [
            shape_json(s)
            for s in engine.shapes(classes, staff, [w.number for w in weeks])
        ],
        "issues": engine.validate(
            weeks, staff, timetable, exceptions, assignments,
            courses, planning_from(settings),
        ),
    }


@app.post("/api/availability")
def availability(body: AvailabilityIn) -> dict:
    """Who could take this slot, and who is already busy in it.

    The interface asks this before offering anyone, so that a person who cannot
    take a class is visibly unavailable rather than a refusal after the fact.
    """
    with db() as conn:
        _, staff, timetable, exceptions, assignments, courses = store.load_all(conn, active_term(conn))

    classes = engine.expand(timetable, exceptions, assignments, courses)
    busy = engine.who_is_free(
        classes,
        [s.id for s in staff],
        body.day,
        store.to_time(body.start),
        store.to_time(body.end),
        body.weeks,
        ignoring=body.timetable_id,
    )
    load = engine.load_by_staff(classes)

    return {
        "staff": [
            {
                "id": s.id,
                "name": s.name,
                "busy_weeks": busy.get(s.id, []),
                "free": not busy.get(s.id),
                "minutes": sum(load.get(s.id, {}).values()),
                "target_minutes": s.target_minutes,
            }
            for s in staff
        ]
    }


@app.post("/api/assign")
def assign(body: AssignIn) -> dict:
    """Put somebody on a class for some or all of the weeks it runs.

    Refused if it would double book them. That refusal is the point of the
    tool: a clash cannot be created and then found later, because the write
    that would create it does not happen.
    """
    with db() as conn:
        _, staff, timetable, exceptions, assignments, courses = store.load_all(conn, active_term(conn))

        if body.staff_id not in {s.id for s in staff}:
            raise HTTPException(400, f"There is no staff member {body.staff_id}.")

        row = next((r for r in timetable if r.id == body.timetable_id), None)
        if row is None:
            raise HTTPException(404, "That class is not in the timetable.")

        weeks = sorted(row.weeks) if body.weeks is None else sorted(set(body.weeks))
        outside = [w for w in weeks if w not in row.weeks]
        if outside:
            raise HTTPException(
                400,
                f"{row.label} does not run in week(s) "
                f"{', '.join(str(w) for w in outside)}.",
            )
        if not weeks:
            raise HTTPException(400, "No weeks were given.")

        classes = engine.expand(timetable, exceptions, assignments, courses)

        conflicts = engine.check_assignment(
            classes, body.staff_id, timetable_id=body.timetable_id, weeks=weeks
        )
        if conflicts:
            raise HTTPException(
                409,
                {
                    "error": "double_booked",
                    "message": _conflict_message(staff, body.staff_id, conflicts),
                    "conflicts": [conflict_json(c) for c in conflicts],
                },
            )

        held = {
            a.week: a.staff_id
            for a in assignments
            if a.timetable_id == body.timetable_id
            and a.week in set(weeks)
            and a.staff_id != body.staff_id
        }
        if held and not body.replace:
            raise HTTPException(
                409,
                {
                    "error": "already_assigned",
                    "message": _handover_message(staff, held),
                    "already": [
                        {"week": w, "staff_id": sid} for w, sid in sorted(held.items())
                    ],
                },
            )

        store.set_assignment(conn, body.timetable_id, weeks, body.staff_id)

    return {"ok": True, "weeks": weeks, "replaced": sorted(held)}


@app.post("/api/unassign")
def unassign(body: UnassignIn) -> dict:
    """Take somebody off a class. The class goes back to needing somebody."""
    with db() as conn:
        removed = store.clear_assignment(conn, body.timetable_id, body.weeks)
    return {"ok": True, "removed": removed}


def _name_for(staff: list[engine.StaffMember], staff_id: str) -> str:
    return next((s.name for s in staff if s.id == staff_id), staff_id)


def _conflict_message(staff, staff_id, conflicts) -> str:
    who = _name_for(staff, staff_id)
    weeks = sorted({c.week for c in conflicts})
    clashing = sorted({c.existing.label for c in conflicts})
    return (
        f"{who} already teaches {' and '.join(clashing)} at that time in "
        f"week{'s' if len(weeks) > 1 else ''} "
        f"{', '.join(str(w) for w in weeks)}."
    )


def _handover_message(staff, held: dict[int, str]) -> str:
    names = sorted({_name_for(staff, sid) for sid in held.values()})
    weeks = sorted(held)
    return (
        f"{' and '.join(names)} currently has week"
        f"{'s' if len(weeks) > 1 else ''} {', '.join(str(w) for w in weeks)}."
    )


# ------------------------------------------------------------ import

@app.post("/api/import/preview")
async def import_preview(file: UploadFile = File(...)) -> dict:
    """Read a timetable file and say what importing it would do.

    Nothing is written. The manager sees the rows, the complaints and the
    staffing that would not survive before deciding.
    """
    data = await file.read()
    try:
        rows, issues = importer.parse(file.filename or "", data)
    except importer.ImportError_ as exc:
        raise HTTPException(400, str(exc))

    with db() as conn:
        _, _, timetable, _, assignments, _ = store.load_all(conn, active_term(conn))

    by_id = {r.id: r for r in timetable}
    incoming = {
        (r["course_code"], r["section"], w)
        for r in rows
        for w in r.get("weeks") or []
    }
    would_drop = []
    for a in assignments:
        row = by_id.get(a.timetable_id)
        if row is None:
            continue
        if (row.course_code, row.section, a.week) not in incoming:
            would_drop.append(
                {
                    "course_code": row.course_code,
                    "section": row.section,
                    "week": a.week,
                    "staff_id": a.staff_id,
                }
            )

    return {
        "rows": rows,
        "issues": issues,
        "replacing": len(timetable),
        "would_drop": sorted(
            would_drop, key=lambda d: (d["course_code"], d["section"], d["week"])
        ),
    }


@app.post("/api/import/commit")
def import_commit(body: CommitIn) -> dict:
    """Write an imported timetable, keeping the staffing that still fits."""
    if not body.rows:
        raise HTTPException(400, "There is nothing to import.")

    with db() as conn:
        term = active_term(conn)
        if body.mode == "append":
            for row in body.rows:
                store.save_timetable_row(conn, row, term=term)
            return {"ok": True, "added": len(body.rows), "kept": 0, "dropped": []}
        result = store.replace_timetable(conn, body.rows, term=active_term(conn))

    return {"ok": True, "added": len(body.rows), **result}


@app.post("/api/courses/import/preview")
async def course_preview(file: UploadFile = File(...)) -> dict:
    """Read a course export and say what it would change. Nothing is written."""
    data = await file.read()
    try:
        rows, issues = importer.parse_courses(file.filename or "", data)
    except importer.ImportError_ as exc:
        raise HTTPException(400, str(exc))

    with db() as conn:
        existing = {c.key for c in store.get_courses(conn)}

    incoming = [
        (r["code"], r["academic_year"], r["semester"], r["occurrence"]) for r in rows
    ]
    offerings = store.offerings_in(rows)
    with db() as conn:
        held = store.get_courses(conn)
    in_those_offerings = [
        c for c in held if (c.academic_year, c.semester) in set(offerings)
    ]

    return {
        "rows": rows,
        "issues": issues,
        "holding": len(existing),
        "new": sum(1 for key in incoming if key not in existing),
        "updating": sum(1 for key in incoming if key in existing),
        "semesters": sorted({r["semester"] for r in rows if r["semester"]}),
        "offerings": [
            {"academic_year": year, "semester": semester}
            for year, semester in offerings
        ],
        # what "replace just these semesters" would drop
        "offering_holds": len(in_those_offerings),
    }


@app.post("/api/courses/import/commit")
def course_commit(body: CourseCommitIn) -> dict:
    """Write catalogue rows. Merging updates in place; replacing wipes first."""
    if not body.rows:
        raise HTTPException(400, "There is nothing to import.")
    if body.mode not in ("merge", "replace_offering", "replace_all"):
        raise HTTPException(400, f"There is no import mode {body.mode!r}.")
    with db() as conn:
        result = store.save_courses(conn, body.rows, mode=body.mode)
    return {"ok": True, **result}


@app.delete("/api/courses/{code}")
def del_course(code: str, academic_year: str = "", semester: str = "",
               occurrence: str = "") -> dict:
    with db() as conn:
        store.delete_course(conn, code, academic_year, semester, occurrence)
    return {"ok": True}


@app.put("/api/settings")
def put_settings(body: SettingsIn) -> dict:
    """Which offering the manager is planning. Both blank means do not narrow."""
    with db() as conn:
        store.set_settings(conn, body.model_dump())
    return {"ok": True}


# ------------------------------------------------------------ records

@app.put("/api/weeks")
def put_weeks(body: WeeksIn) -> dict:
    with db() as conn:
        store.replace_weeks(conn, body.weeks, term=active_term(conn))
    return {"ok": True}


@app.post("/api/weeks/generate")
def generate_weeks(body: WeeksGenerateIn) -> dict:
    """Build a term's calendar from when it starts, how long, and the breaks."""
    if body.count < 1:
        raise HTTPException(400, "A semester needs at least one teaching week.")
    if body.count > 52:
        raise HTTPException(400, "That is more weeks than a year has.")

    try:
        start = date.fromisoformat(body.first_monday)
        breaks = [
            (date.fromisoformat(b.starts), date.fromisoformat(b.ends))
            for b in body.breaks
        ]
    except ValueError as exc:
        raise HTTPException(400, f"That is not a date the tool can read: {exc}")

    for first, last in breaks:
        if last < first:
            raise HTTPException(400, "A break ends before it starts.")

    weeks = engine.build_weeks(start, body.count, breaks)
    with db() as conn:
        store.replace_weeks(
            conn,
            [
                {
                    "number": w.number,
                    "starts": w.starts.isoformat(),
                    "ends": w.ends.isoformat(),
                    "note": w.note,
                }
                for w in weeks
            ],
            term=active_term(conn),
        )
    return {"ok": True, "weeks": [week_json(w) for w in weeks]}


@app.post("/api/staff")
def post_staff(body: StaffIn) -> dict:
    try:
        with db() as conn:
            store.save_staff(conn, body.model_dump())
    except sqlite3.IntegrityError:
        raise HTTPException(409, f"Staff id {body.id} is already in use.")
    return {"ok": True}


@app.put("/api/staff/{staff_id}")
def put_staff(staff_id: str, body: StaffIn) -> dict:
    with db() as conn:
        store.save_staff(conn, body.model_dump(), original_id=staff_id)
    return {"ok": True}


@app.delete("/api/staff/{staff_id}")
def del_staff(staff_id: str) -> dict:
    with db() as conn:
        store.delete_staff(conn, staff_id)
    return {"ok": True}


@app.post("/api/timetable")
def post_timetable(body: TimetableIn) -> dict:
    with db() as conn:
        return {"id": store.save_timetable_row(conn, body.model_dump(), term=active_term(conn))}


@app.put("/api/timetable/{row_id}")
def put_timetable(row_id: int, body: TimetableIn) -> dict:
    with db() as conn:
        store.save_timetable_row(conn, body.model_dump(), row_id=row_id,
                                 term=active_term(conn))
    return {"ok": True}


@app.delete("/api/timetable/{row_id}")
def del_timetable(row_id: int) -> dict:
    with db() as conn:
        store.delete_timetable_row(conn, row_id)
    return {"ok": True}


@app.post("/api/exceptions")
def post_exception(body: ExceptionIn) -> dict:
    _refuse_staffed_change(body)
    with db() as conn:
        _refuse_conflicting_add(conn, body)
        return {"id": store.save_exception(conn, body.model_dump(), term=active_term(conn))}


@app.put("/api/exceptions/{row_id}")
def put_exception(row_id: int, body: ExceptionIn) -> dict:
    _refuse_staffed_change(body)
    with db() as conn:
        _refuse_conflicting_add(conn, body, row_id=row_id)
        store.save_exception(conn, body.model_dump(), row_id=row_id,
                             term=active_term(conn))
    return {"ok": True}


@app.delete("/api/exceptions/{row_id}")
def del_exception(row_id: int) -> dict:
    with db() as conn:
        store.delete_exception(conn, row_id)
    return {"ok": True}


def _refuse_staffed_change(body: ExceptionIn) -> None:
    """Staffing is an assignment, including for one week only."""
    if body.action != engine.Action.ADD.value and body.staff_id:
        raise HTTPException(
            400,
            "Exceptions do not carry staff. Assign that week to somebody on the "
            "Planner instead.",
        )


def _refuse_conflicting_add(conn, body: ExceptionIn, row_id: int | None = None) -> None:
    """An added class is staffed on the spot, so it is checked on the spot."""
    if body.action != engine.Action.ADD.value or not body.staff_id:
        return

    _, staff, timetable, exceptions, assignments, courses = store.load_all(conn, active_term(conn))
    if body.staff_id not in {s.id for s in staff}:
        raise HTTPException(400, f"There is no staff member {body.staff_id}.")
    if not (body.day and body.start and body.end):
        return

    others = [e for e in exceptions if e.id != row_id]
    proposed = engine.ExceptionRow(
        id=-1,
        week=body.week,
        course_code=body.course_code,
        section=body.section,
        action=engine.Action.ADD,
        day=body.day,
        start=store.to_time(body.start),
        end=store.to_time(body.end),
        staff_id=body.staff_id,
    )
    classes = engine.expand(timetable, others + [proposed], assignments, courses)
    conflicts = engine.check_assignment(classes, body.staff_id, exception_id=-1)
    if conflicts:
        raise HTTPException(
            409,
            {
                "error": "double_booked",
                "message": _conflict_message(staff, body.staff_id, conflicts),
                "conflicts": [conflict_json(c) for c in conflicts],
            },
        )


@app.post("/api/sample-data")
def reload_sample() -> dict:
    with db() as conn:
        seed.clear(conn)
        seed.load(conn)
    return {"ok": True}


@app.delete("/api/sample-data")
def remove_sample() -> dict:
    """Take out what the app invented, leaving anything imported or typed."""
    with db() as conn:
        removed = store.remove_sample(conn)
    return {"ok": True, "removed": removed}


@app.delete("/api/all-data")
def clear_all() -> dict:
    with db() as conn:
        seed.clear(conn)
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(HERE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


if __name__ == "__main__":
    print("\n  Timetable staffing running at http://127.0.0.1:8000\n")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
