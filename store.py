"""SQLite storage for the staffing tool.

This is the only module that knows the data lives in a database. It converts
between rows and the plain objects in engine.py, and nothing else. Keep domain
rules out of here: if a rule about how timetables behave ends up in this file,
it belongs in the engine instead.
"""

from __future__ import annotations

import sqlite3
from datetime import date, time
from pathlib import Path

from engine import (
    Action, Assignment, Course, ExceptionRow, StaffMember, TimetableRow, Week,
)

DB_PATH = Path(__file__).parent / "timetable.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS weeks (
    number  INTEGER PRIMARY KEY,
    starts  TEXT NOT NULL,
    ends    TEXT NOT NULL,
    note    TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS staff (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    email           TEXT NOT NULL DEFAULT '',
    target_minutes  INTEGER
);

-- The catalogue, as exported from the student management system. Identity is
-- the whole offering: one code can run in both semesters.
CREATE TABLE IF NOT EXISTS courses (
    code                        TEXT NOT NULL,
    academic_year               TEXT NOT NULL DEFAULT '',
    semester                    TEXT NOT NULL DEFAULT '',
    occurrence                  TEXT NOT NULL DEFAULT '',
    name                        TEXT NOT NULL DEFAULT '',
    college                     TEXT NOT NULL DEFAULT '',
    programme                   TEXT NOT NULL DEFAULT '',
    coordinator                 TEXT NOT NULL DEFAULT '',
    coordinator_email           TEXT NOT NULL DEFAULT '',
    offering_coordinator        TEXT NOT NULL DEFAULT '',
    offering_coordinator_email  TEXT NOT NULL DEFAULT '',
    grade_reviewer              TEXT NOT NULL DEFAULT '',
    grade_reviewer_email        TEXT NOT NULL DEFAULT '',
    department                  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (code, academic_year, semester, occurrence)
);

-- A course is named in one place, so the timetable does not carry a title.
CREATE TABLE IF NOT EXISTS timetable (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code   TEXT NOT NULL,
    section       TEXT NOT NULL,
    day           TEXT NOT NULL,
    start         TEXT NOT NULL,
    end           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS timetable_weeks (
    timetable_id  INTEGER NOT NULL,
    week          INTEGER NOT NULL,
    PRIMARY KEY (timetable_id, week),
    FOREIGN KEY (timetable_id) REFERENCES timetable (id) ON DELETE CASCADE
);

-- One person per class per week, enforced by the primary key rather than by
-- code. Splitting a semester is two sets of rows; a substitution is one row.
CREATE TABLE IF NOT EXISTS assignments (
    timetable_id  INTEGER NOT NULL,
    week          INTEGER NOT NULL,
    staff_id      TEXT NOT NULL,
    PRIMARY KEY (timetable_id, week),
    FOREIGN KEY (timetable_id) REFERENCES timetable (id) ON DELETE CASCADE,
    FOREIGN KEY (staff_id) REFERENCES staff (id)
        ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS exceptions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    week          INTEGER NOT NULL,
    course_code   TEXT NOT NULL,
    section       TEXT NOT NULL,
    action        TEXT NOT NULL,
    day           TEXT,
    start         TEXT,
    end           TEXT,
    staff_id      TEXT,
    note          TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS ix_courses_code ON courses (code);
CREATE INDEX IF NOT EXISTS ix_tt_weeks ON timetable_weeks (week);
CREATE INDEX IF NOT EXISTS ix_assign_staff ON assignments (staff_id);
CREATE INDEX IF NOT EXISTS ix_exc_key ON exceptions (week, course_code, section);
"""


# ------------------------------------------------------------ conversions

def to_time(value: str | None) -> time | None:
    if not value:
        return None
    hh, mm = value.split(":")[:2]
    return time(int(hh), int(mm))


def from_time(value: time | None) -> str | None:
    return None if value is None else f"{value.hour:02d}:{value.minute:02d}"


def blank_to_none(value):
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


# ------------------------------------------------------------ connection

def connect(path: Path | str | None = None) -> sqlite3.Connection:
    # Resolved at call time, not import time, so tests and callers can point
    # this somewhere else.
    conn = sqlite3.connect(path if path is not None else DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def is_empty(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT COUNT(*) FROM timetable").fetchone()[0] == 0


# ------------------------------------------------------------ reading

def get_weeks(conn) -> list[Week]:
    return [
        Week(
            number=r["number"],
            starts=date.fromisoformat(r["starts"]),
            ends=date.fromisoformat(r["ends"]),
            note=r["note"],
        )
        for r in conn.execute("SELECT * FROM weeks ORDER BY number")
    ]


def get_staff(conn) -> list[StaffMember]:
    return [
        StaffMember(
            id=r["id"],
            name=r["name"],
            email=r["email"],
            target_minutes=r["target_minutes"],
        )
        for r in conn.execute("SELECT * FROM staff ORDER BY name")
    ]


COURSE_FIELDS = (
    "code", "academic_year", "semester", "occurrence", "name", "college",
    "programme", "coordinator", "coordinator_email", "offering_coordinator",
    "offering_coordinator_email", "grade_reviewer", "grade_reviewer_email",
    "department",
)


def get_courses(conn) -> list[Course]:
    return [
        Course(**{field: r[field] for field in COURSE_FIELDS})
        for r in conn.execute(
            "SELECT * FROM courses ORDER BY code, academic_year, semester, occurrence"
        )
    ]


def get_settings(conn) -> dict:
    return {r["key"]: r["value"] for r in conn.execute("SELECT * FROM settings")}


def get_timetable(conn) -> list[TimetableRow]:
    weeks_by_row: dict[int, set[int]] = {}
    for r in conn.execute("SELECT * FROM timetable_weeks"):
        weeks_by_row.setdefault(r["timetable_id"], set()).add(r["week"])

    return [
        TimetableRow(
            id=r["id"],
            course_code=r["course_code"],
            section=r["section"],
            day=r["day"],
            start=to_time(r["start"]),
            end=to_time(r["end"]),
            weeks=frozenset(weeks_by_row.get(r["id"], set())),
        )
        for r in conn.execute(
            "SELECT * FROM timetable ORDER BY course_code, section, id"
        )
    ]


def get_assignments(conn) -> list[Assignment]:
    return [
        Assignment(
            timetable_id=r["timetable_id"], week=r["week"], staff_id=r["staff_id"]
        )
        for r in conn.execute(
            "SELECT * FROM assignments ORDER BY timetable_id, week"
        )
    ]


def get_exceptions(conn) -> list[ExceptionRow]:
    return [
        ExceptionRow(
            id=r["id"],
            week=r["week"],
            course_code=r["course_code"],
            section=r["section"],
            action=Action(r["action"]),
            day=r["day"],
            start=to_time(r["start"]),
            end=to_time(r["end"]),
            staff_id=r["staff_id"],
            note=r["note"],
        )
        for r in conn.execute(
            "SELECT * FROM exceptions ORDER BY week, course_code, section, id"
        )
    ]


def load_all(conn):
    return (
        get_weeks(conn),
        get_staff(conn),
        get_timetable(conn),
        get_exceptions(conn),
        get_assignments(conn),
        get_courses(conn),
    )


# ------------------------------------------------------------ writing

def replace_weeks(conn, rows: list[dict]) -> None:
    with conn:
        conn.execute("DELETE FROM weeks")
        conn.executemany(
            "INSERT INTO weeks (number, starts, ends, note) VALUES (?, ?, ?, ?)",
            [
                (int(r["number"]), r["starts"], r["ends"], r.get("note") or "")
                for r in rows
            ],
        )


def save_staff(conn, row: dict, original_id: str | None = None) -> str:
    target = row.get("target_minutes")
    target = None if target in ("", None) else int(target)
    with conn:
        if original_id:
            conn.execute(
                "UPDATE staff SET id = ?, name = ?, email = ?, target_minutes = ?"
                " WHERE id = ?",
                (row["id"], row["name"], row.get("email") or "", target, original_id),
            )
            # assignments follow the rename through ON UPDATE CASCADE; added
            # classes carry their own staff id and do not.
            if row["id"] != original_id:
                conn.execute(
                    "UPDATE exceptions SET staff_id = ? WHERE staff_id = ?",
                    (row["id"], original_id),
                )
        else:
            conn.execute(
                "INSERT INTO staff (id, name, email, target_minutes)"
                " VALUES (?, ?, ?, ?)",
                (row["id"], row["name"], row.get("email") or "", target),
            )
    return row["id"]


def delete_staff(conn, staff_id: str) -> None:
    """Remove somebody, and with them their assignments.

    Their classes go back to being uncovered, which is the truth: nobody is
    teaching them now.
    """
    with conn:
        conn.execute("DELETE FROM staff WHERE id = ?", (staff_id,))
        conn.execute(
            "UPDATE exceptions SET staff_id = NULL WHERE staff_id = ?", (staff_id,)
        )


def _write_weeks_for_row(conn, timetable_id: int, weeks) -> None:
    conn.execute("DELETE FROM timetable_weeks WHERE timetable_id = ?", (timetable_id,))
    conn.executemany(
        "INSERT INTO timetable_weeks (timetable_id, week) VALUES (?, ?)",
        [(timetable_id, int(w)) for w in sorted(set(weeks))],
    )


def save_timetable_row(conn, row: dict, row_id: int | None = None) -> int:
    values = (
        row["course_code"],
        row["section"],
        row["day"],
        row["start"],
        row["end"],
    )
    weeks = {int(w) for w in (row.get("weeks") or [])}
    with conn:
        if row_id is None:
            cur = conn.execute(
                "INSERT INTO timetable (course_code, section, day, start, end)"
                " VALUES (?, ?, ?, ?, ?)",
                values,
            )
            row_id = cur.lastrowid
        else:
            conn.execute(
                "UPDATE timetable SET course_code = ?, section = ?,"
                " day = ?, start = ?, end = ? WHERE id = ?",
                values + (row_id,),
            )
            # A week the class no longer runs in cannot stay staffed.
            existing = [
                r["week"]
                for r in conn.execute(
                    "SELECT week FROM assignments WHERE timetable_id = ?", (row_id,)
                )
            ]
            gone = [w for w in existing if w not in weeks]
            if gone:
                conn.executemany(
                    "DELETE FROM assignments WHERE timetable_id = ? AND week = ?",
                    [(row_id, w) for w in gone],
                )
        _write_weeks_for_row(conn, row_id, weeks)
    return row_id


def delete_timetable_row(conn, row_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM assignments WHERE timetable_id = ?", (row_id,))
        conn.execute("DELETE FROM timetable_weeks WHERE timetable_id = ?", (row_id,))
        conn.execute("DELETE FROM timetable WHERE id = ?", (row_id,))


def set_assignment(conn, timetable_id: int, weeks: list[int], staff_id: str) -> int:
    """Put somebody on a class for these weeks, replacing whoever held them."""
    with conn:
        conn.executemany(
            "INSERT INTO assignments (timetable_id, week, staff_id) VALUES (?, ?, ?)"
            " ON CONFLICT (timetable_id, week) DO UPDATE SET staff_id = excluded.staff_id",
            [(timetable_id, int(w), staff_id) for w in sorted(set(weeks))],
        )
    return len(set(weeks))


def clear_assignment(conn, timetable_id: int, weeks: list[int] | None = None) -> int:
    """Take somebody off a class. Weeks of None means every week it runs."""
    with conn:
        if weeks is None:
            cur = conn.execute(
                "DELETE FROM assignments WHERE timetable_id = ?", (timetable_id,)
            )
        else:
            cur = conn.executemany(
                "DELETE FROM assignments WHERE timetable_id = ? AND week = ?",
                [(timetable_id, int(w)) for w in sorted(set(weeks))],
            )
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0


def save_exception(conn, row: dict, row_id: int | None = None) -> int:
    values = (
        int(row["week"]),
        row["course_code"],
        row["section"],
        row["action"],
        blank_to_none(row.get("day")),
        blank_to_none(row.get("start")),
        blank_to_none(row.get("end")),
        blank_to_none(row.get("staff_id")),
        row.get("note") or "",
    )
    with conn:
        if row_id is None:
            cur = conn.execute(
                "INSERT INTO exceptions (week, course_code, section, action,"
                " day, start, end, staff_id, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )
            return cur.lastrowid
        conn.execute(
            "UPDATE exceptions SET week = ?, course_code = ?, section = ?, action = ?,"
            " day = ?, start = ?, end = ?, staff_id = ?, note = ? WHERE id = ?",
            values + (row_id,),
        )
    return row_id


def delete_exception(conn, row_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM exceptions WHERE id = ?", (row_id,))


# ------------------------------------------------------------ courses

def save_courses(conn, rows: list[dict], replace: bool = False) -> dict:
    """Write catalogue rows, keyed on the whole offering.

    Re-importing the same export is not meant to double it up, so a row that
    already exists is overwritten rather than added beside itself. Replacing is
    the deliberate, destructive version and has to be asked for: an export is
    often one semester, and wiping the other one silently would be wrong.
    """
    before = {c.key for c in get_courses(conn)}
    values = [
        tuple(str(row.get(field) or "") for field in COURSE_FIELDS)
        for row in rows
    ]
    placeholders = ", ".join("?" * len(COURSE_FIELDS))

    with conn:
        if replace:
            conn.execute("DELETE FROM courses")
        conn.executemany(
            f"INSERT OR REPLACE INTO courses ({', '.join(COURSE_FIELDS)})"
            f" VALUES ({placeholders})",
            values,
        )

    after = {c.key for c in get_courses(conn)}
    incoming = {
        (str(r.get("code") or ""), str(r.get("academic_year") or ""),
         str(r.get("semester") or ""), str(r.get("occurrence") or ""))
        for r in rows
    }
    return {
        "added": len(incoming - before),
        "updated": len(incoming & before),
        "removed": len(before - after),
        "total": len(after),
    }


def delete_course(conn, code: str, academic_year: str, semester: str, occurrence: str) -> None:
    with conn:
        conn.execute(
            "DELETE FROM courses WHERE code = ? AND academic_year = ?"
            " AND semester = ? AND occurrence = ?",
            (code, academic_year, semester, occurrence),
        )


def set_settings(conn, values: dict) -> None:
    with conn:
        conn.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            [(str(k), str(v if v is not None else "")) for k, v in values.items()],
        )


# ------------------------------------------------------------ import

def replace_timetable(conn, rows: list[dict]) -> dict:
    """Swap in a freshly imported timetable, keeping staffing where it still fits.

    The timetable is somebody else's document and gets reissued. Staffing is the
    manager's work and should survive that, so assignments are re-attached by
    course, section and week. Anything that no longer has a class under it is
    reported rather than dropped quietly.
    """
    old_rows = get_timetable(conn)
    old_assignments = get_assignments(conn)
    by_id = {r.id: r for r in old_rows}

    held: dict[tuple[str, str, int], str] = {}
    for a in old_assignments:
        row = by_id.get(a.timetable_id)
        if row is not None:
            held[(row.course_code, row.section, a.week)] = a.staff_id

    with conn:
        conn.execute("DELETE FROM assignments")
        conn.execute("DELETE FROM timetable_weeks")
        conn.execute("DELETE FROM timetable")

    kept, dropped = 0, []
    for row in rows:
        new_id = save_timetable_row(conn, row)
        for week in sorted({int(w) for w in row.get("weeks") or []}):
            staff_id = held.pop((row["course_code"], row["section"], week), None)
            if staff_id is not None:
                set_assignment(conn, new_id, [week], staff_id)
                kept += 1

    for (code, section, week), staff_id in sorted(held.items()):
        dropped.append(
            {"course_code": code, "section": section, "week": week, "staff_id": staff_id}
        )

    return {"kept": kept, "dropped": dropped}
