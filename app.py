"""Web application for the timetable clash tool.

Run it with:

    python app.py

then open http://127.0.0.1:8000 in a browser. The database is created and
seeded with sample data on first run.

This layer translates between HTTP and the engine. It holds no rules about how
timetables behave; those all live in engine.py.
"""

from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import engine
import seed
import store

HERE = Path(__file__).parent

# Bumped whenever the API changes. The browser reads app.js fresh from disk on
# every load, but the routes live in this process, so an unrestarted server
# serves a new front end against old endpoints. The front end compares this
# against its own copy and says so rather than failing with a bare 404.
VERSION = "2026-08-31.3"


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
        if store.is_empty(conn):
            seed.load(conn)
    yield


app = FastAPI(title="Timetable clashes", lifespan=lifespan)


# ------------------------------------------------------------ request bodies

class StaffIn(BaseModel):
    id: str
    name: str
    email: str = ""


class TimetableIn(BaseModel):
    course_code: str
    course_title: str = ""
    section: str
    staff_id: str | None = None
    day: str
    start: str
    end: str
    weeks: list[int] = Field(default_factory=list)


class ExceptionIn(BaseModel):
    week: int
    course_code: str
    section: str
    action: str
    staff_id: str | None = None
    day: str | None = None
    start: str | None = None
    end: str | None = None
    note: str = ""


class WeeksIn(BaseModel):
    weeks: list[dict]


class AvailabilityIn(BaseModel):
    day: str
    start: str
    end: str
    weeks: list[int]
    course_code: str | None = None
    section: str | None = None


class ReassignIn(BaseModel):
    course_code: str
    section: str
    staff_id: str
    weeks: list[int] | None = None   # None means every week the class runs


# ------------------------------------------------------------ serialisation

def week_json(w: engine.Week) -> dict:
    return {
        "number": w.number,
        "starts": w.starts.isoformat(),
        "ends": w.ends.isoformat(),
        "note": w.note,
    }


def timetable_json(r: engine.TimetableRow) -> dict:
    return {
        "id": r.id,
        "course_code": r.course_code,
        "course_title": r.course_title,
        "section": r.section,
        "staff_id": r.staff_id,
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
        "staff_id": e.staff_id,
        "day": e.day,
        "start": store.from_time(e.start),
        "end": store.from_time(e.end),
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
        "timetable_row_id": c.timetable_row_id,
        "exception_id": c.exception_id,
    }


# ------------------------------------------------------------ routes

@app.get("/api/state")
def state() -> dict:
    with db() as conn:
        weeks, staff, timetable, exceptions = store.load_all(conn)

    classes = engine.expand(timetable, exceptions)
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

    return {
        "version": VERSION,
        "weeks": [week_json(w) for w in weeks],
        "staff": [{"id": s.id, "name": s.name, "email": s.email} for s in staff],
        "timetable": [timetable_json(r) for r in timetable],
        "exceptions": [exception_json(e) for e in exceptions],
        "classes": [
            class_json(c) | {"id": i, "clashing": i in clashing}
            for i, c in enumerate(classes)
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
        "load": engine.load_by_staff(classes),
        "issues": engine.validate(weeks, staff, timetable, exceptions),
    }


@app.post("/api/availability")
def availability(body: AvailabilityIn) -> dict:
    """Who could take this slot, and who is already busy in it."""
    with db() as conn:
        _, staff, timetable, exceptions = store.load_all(conn)

    classes = engine.expand(timetable, exceptions)
    ignoring = (
        (body.course_code, body.section)
        if body.course_code and body.section else None
    )
    busy = engine.who_is_free(
        classes,
        [s.id for s in staff],
        body.day,
        store.to_time(body.start),
        store.to_time(body.end),
        body.weeks,
        ignoring=ignoring,
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
            }
            for s in staff
        ]
    }


@app.post("/api/reassign")
def reassign(body: ReassignIn) -> dict:
    """Hand a class to someone else.

    Staffing lives in the timetable, so that is what changes. Reassigning part
    of a semester splits the timetable row in two: the original keeps the weeks
    it still covers, and a new row carries the reassigned weeks. That is the
    same shape you would use for a lecturer who changes partway through, and it
    keeps the timetable honest about who teaches what.

    This never creates an exception. Exceptions are for weeks that genuinely
    depart from the timetable, not a way of papering over its staffing. Two
    existing records are updated rather than added to, because for those weeks
    they already are where the truth lives:

      - a class that exists only as an added exception has no timetable row
      - a change exception that already overrides staff would otherwise mask
        the reassignment and leave the clash in place
    """
    with db() as conn:
        _, staff, timetable, exceptions = store.load_all(conn)
        if body.staff_id not in {s.id for s in staff}:
            raise HTTPException(400, f"There is no staff member {body.staff_id}.")

        rows = [
            r for r in timetable
            if r.course_code == body.course_code and r.section == body.section
        ]
        matching_exceptions = [
            e for e in exceptions
            if e.course_code == body.course_code and e.section == body.section
        ]
        if not rows and not matching_exceptions:
            raise HTTPException(
                404, f"{body.course_code} {body.section} is not in the timetable.")

        wanted = None if body.weeks is None else set(body.weeks)
        in_scope = lambda week: wanted is None or week in wanted

        def write_exception(e, staff_id):
            store.save_exception(
                conn,
                {
                    "week": e.week, "course_code": e.course_code,
                    "section": e.section, "action": e.action.value,
                    "staff_id": staff_id, "day": e.day,
                    "start": store.from_time(e.start),
                    "end": store.from_time(e.end), "note": e.note,
                },
                row_id=e.id,
            )

        def write_row(r, staff_id, weeks, row_id):
            return store.save_timetable_row(
                conn,
                {
                    "course_code": r.course_code, "course_title": r.course_title,
                    "section": r.section, "staff_id": staff_id, "day": r.day,
                    "start": store.from_time(r.start),
                    "end": store.from_time(r.end), "weeks": sorted(weeks),
                },
                row_id=row_id,
            )

        touched, split = 0, False

        for e in matching_exceptions:
            if not in_scope(e.week):
                continue
            if e.action is engine.Action.ADD:
                write_exception(e, body.staff_id)
                touched += 1
            elif e.action is engine.Action.CHANGE and e.staff_id is not None:
                write_exception(e, body.staff_id)
                touched += 1

        for r in rows:
            target = set(r.weeks) if wanted is None else set(r.weeks) & wanted
            if not target:
                continue
            remaining = set(r.weeks) - target
            if remaining:
                write_row(r, r.staff_id, remaining, r.id)   # keeps its own weeks
                write_row(r, body.staff_id, target, None)   # new row, new staff
                split = True
            else:
                write_row(r, body.staff_id, target, r.id)
            touched += 1

    return {"changed": "timetable", "rows": touched, "split": split}


@app.put("/api/weeks")
def put_weeks(body: WeeksIn) -> dict:
    with db() as conn:
        store.replace_weeks(conn, body.weeks)
    return {"ok": True}


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
        return {"id": store.save_timetable_row(conn, body.model_dump())}


@app.put("/api/timetable/{row_id}")
def put_timetable(row_id: int, body: TimetableIn) -> dict:
    with db() as conn:
        store.save_timetable_row(conn, body.model_dump(), row_id=row_id)
    return {"ok": True}


@app.delete("/api/timetable/{row_id}")
def del_timetable(row_id: int) -> dict:
    with db() as conn:
        store.delete_timetable_row(conn, row_id)
    return {"ok": True}


@app.post("/api/exceptions")
def post_exception(body: ExceptionIn) -> dict:
    with db() as conn:
        return {"id": store.save_exception(conn, body.model_dump())}


@app.put("/api/exceptions/{row_id}")
def put_exception(row_id: int, body: ExceptionIn) -> dict:
    with db() as conn:
        store.save_exception(conn, body.model_dump(), row_id=row_id)
    return {"ok": True}


@app.delete("/api/exceptions/{row_id}")
def del_exception(row_id: int) -> dict:
    with db() as conn:
        store.delete_exception(conn, row_id)
    return {"ok": True}


@app.post("/api/sample-data")
def reload_sample() -> dict:
    with db() as conn:
        seed.clear(conn)
        seed.load(conn)
    return {"ok": True}


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
    print("\n  Timetable clashes running at http://127.0.0.1:8000\n")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
