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

from engine import Action, Assignment, ExceptionRow, StaffMember, TimetableRow, Week

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

CREATE TABLE IF NOT EXISTS timetable (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code   TEXT NOT NULL,
    course_title  TEXT NOT NULL DEFAULT '',
    section       TEXT NOT NULL,
    day           TEXT NOT NULL,
    start         TEXT NOT NULL,
    end           TEXT NOT NULL
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


def get_timetable(conn) -> list[TimetableRow]:
    weeks_by_row: dict[int, set[int]] = {}
    for r in conn.execute("SELECT * FROM timetable_weeks"):
        weeks_by_row.setdefault(r["timetable_id"], set()).add(r["week"])

    return [
        TimetableRow(
            id=r["id"],
            course_code=r["course_code"],
            course_title=r["course_title"],
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
        row.get("course_title") or "",
        row["section"],
        row["day"],
        row["start"],
        row["end"],
    )
    weeks = {int(w) for w in (row.get("weeks") or [])}
    with conn:
        if row_id is None:
            cur = conn.execute(
                "INSERT INTO timetable (course_code, course_title, section,"
                " day, start, end) VALUES (?, ?, ?, ?, ?, ?)",
                values,
            )
            row_id = cur.lastrowid
        else:
            conn.execute(
                "UPDATE timetable SET course_code = ?, course_title = ?, section = ?,"
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
