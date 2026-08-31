"""SQLite storage for the timetable tool.

This is the only module that knows the data lives in a database. It converts
between rows and the plain objects in engine.py, and nothing else. Keep
domain rules out of here: if a rule about how timetables behave ends up in this
file, it belongs in the engine instead.
"""

from __future__ import annotations

import sqlite3
from datetime import date, time
from pathlib import Path

from engine import Action, ExceptionRow, StaffMember, TimetableRow, Week

DB_PATH = Path(__file__).parent / "timetable.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS weeks (
    number  INTEGER PRIMARY KEY,
    starts  TEXT NOT NULL,
    ends    TEXT NOT NULL,
    note    TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS staff (
    id      TEXT PRIMARY KEY,
    name    TEXT NOT NULL,
    email   TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS timetable (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code   TEXT NOT NULL,
    course_title  TEXT NOT NULL DEFAULT '',
    section       TEXT NOT NULL,
    staff_id      TEXT,
    day           TEXT NOT NULL,
    start         TEXT NOT NULL,
    end           TEXT NOT NULL,
    FOREIGN KEY (staff_id) REFERENCES staff (id)
        ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS timetable_weeks (
    timetable_id  INTEGER NOT NULL,
    week          INTEGER NOT NULL,
    PRIMARY KEY (timetable_id, week),
    FOREIGN KEY (timetable_id) REFERENCES timetable (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS exceptions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    week          INTEGER NOT NULL,
    course_code   TEXT NOT NULL,
    section       TEXT NOT NULL,
    action        TEXT NOT NULL,
    staff_id      TEXT,
    day           TEXT,
    start         TEXT,
    end           TEXT,
    note          TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS ix_tt_weeks ON timetable_weeks (week);
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
        StaffMember(id=r["id"], name=r["name"], email=r["email"])
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
            staff_id=r["staff_id"],
            day=r["day"],
            start=to_time(r["start"]),
            end=to_time(r["end"]),
            weeks=frozenset(weeks_by_row.get(r["id"], set())),
        )
        for r in conn.execute(
            "SELECT * FROM timetable ORDER BY course_code, section, id"
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
            staff_id=r["staff_id"],
            day=r["day"],
            start=to_time(r["start"]),
            end=to_time(r["end"]),
            note=r["note"],
        )
        for r in conn.execute(
            "SELECT * FROM exceptions ORDER BY week, course_code, section, id"
        )
    ]


def load_all(conn):
    return get_weeks(conn), get_staff(conn), get_timetable(conn), get_exceptions(conn)


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
    with conn:
        if original_id:
            conn.execute(
                "UPDATE staff SET id = ?, name = ?, email = ? WHERE id = ?",
                (row["id"], row["name"], row.get("email") or "", original_id),
            )
            if row["id"] != original_id:
                conn.execute(
                    "UPDATE timetable SET staff_id = ? WHERE staff_id = ?",
                    (row["id"], original_id),
                )
                conn.execute(
                    "UPDATE exceptions SET staff_id = ? WHERE staff_id = ?",
                    (row["id"], original_id),
                )
        else:
            conn.execute(
                "INSERT INTO staff (id, name, email) VALUES (?, ?, ?)",
                (row["id"], row["name"], row.get("email") or ""),
            )
    return row["id"]


def delete_staff(conn, staff_id: str) -> None:
    with conn:
        conn.execute("DELETE FROM staff WHERE id = ?", (staff_id,))


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
        blank_to_none(row.get("staff_id")),
        row["day"],
        row["start"],
        row["end"],
    )
    with conn:
        if row_id is None:
            cur = conn.execute(
                "INSERT INTO timetable (course_code, course_title, section, staff_id,"
                " day, start, end) VALUES (?, ?, ?, ?, ?, ?, ?)",
                values,
            )
            row_id = cur.lastrowid
        else:
            conn.execute(
                "UPDATE timetable SET course_code = ?, course_title = ?, section = ?,"
                " staff_id = ?, day = ?, start = ?, end = ? WHERE id = ?",
                values + (row_id,),
            )
        _write_weeks_for_row(conn, row_id, row.get("weeks") or [])
    return row_id


def delete_timetable_row(conn, row_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM timetable_weeks WHERE timetable_id = ?", (row_id,))
        conn.execute("DELETE FROM timetable WHERE id = ?", (row_id,))


def save_exception(conn, row: dict, row_id: int | None = None) -> int:
    values = (
        int(row["week"]),
        row["course_code"],
        row["section"],
        row["action"],
        blank_to_none(row.get("staff_id")),
        blank_to_none(row.get("day")),
        blank_to_none(row.get("start")),
        blank_to_none(row.get("end")),
        row.get("note") or "",
    )
    with conn:
        if row_id is None:
            cur = conn.execute(
                "INSERT INTO exceptions (week, course_code, section, action, staff_id,"
                " day, start, end, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )
            return cur.lastrowid
        conn.execute(
            "UPDATE exceptions SET week = ?, course_code = ?, section = ?, action = ?,"
            " staff_id = ?, day = ?, start = ?, end = ?, note = ? WHERE id = ?",
            values + (row_id,),
        )
    return row_id


def delete_exception(conn, row_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM exceptions WHERE id = ?", (row_id,))
