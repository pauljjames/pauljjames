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

# A term is a (academic_year, semester) pair. The plan belongs to one; the
# course catalogue does not, since a course keeps its name across terms.
WEEKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS weeks (
    academic_year  TEXT NOT NULL DEFAULT '',
    semester       TEXT NOT NULL DEFAULT '',
    number         INTEGER NOT NULL,
    starts         TEXT NOT NULL,
    ends           TEXT NOT NULL,
    note           TEXT NOT NULL DEFAULT '',
    is_sample      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (academic_year, semester, number)
);
"""

SCHEMA = WEEKS_SCHEMA + """

CREATE TABLE IF NOT EXISTS staff (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    email           TEXT NOT NULL DEFAULT '',
    target_minutes  INTEGER,
    is_sample  INTEGER NOT NULL DEFAULT 0
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
    is_sample                   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (code, academic_year, semester, occurrence)
);

-- A course is named in one place, so the timetable does not carry a title.
CREATE TABLE IF NOT EXISTS timetable (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    academic_year  TEXT NOT NULL DEFAULT '',
    semester       TEXT NOT NULL DEFAULT '',
    course_code    TEXT NOT NULL,
    section        TEXT NOT NULL,
    day            TEXT NOT NULL,
    start          TEXT NOT NULL,
    end            TEXT NOT NULL,
    is_sample      INTEGER NOT NULL DEFAULT 0
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
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    academic_year  TEXT NOT NULL DEFAULT '',
    semester       TEXT NOT NULL DEFAULT '',
    week          INTEGER NOT NULL,
    course_code   TEXT NOT NULL,
    section       TEXT NOT NULL,
    action        TEXT NOT NULL,
    day           TEXT,
    start         TEXT,
    end           TEXT,
    staff_id      TEXT,
    note          TEXT NOT NULL DEFAULT '',
    is_sample     INTEGER NOT NULL DEFAULT 0
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

# Databases this process has already prepared. The schema is set up the first
# time a database is opened rather than only when the application's startup hook
# runs, because nothing about how the app is launched should be able to leave
# requests hitting an unprepared file: a wrapper that swallows the lifespan, a
# different server, lifespan turned off, or a second database path all did.
_PREPARED: set[str] = set()


def connect(path: Path | str | None = None, prepare: bool = True) -> sqlite3.Connection:
    # Resolved at call time, not import time, so tests and callers can point
    # this somewhere else.
    target = Path(path if path is not None else DB_PATH)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # prepare=False is for callers building a database deliberately, such as the
    # test that constructs one in an older shape to check the migration.
    if prepare:
        key = str(target.resolve())
        if key not in _PREPARED:
            init(conn)
            _PREPARED.add(key)
    return conn


# Set once the database has been through setup, so a database somebody has
# deliberately emptied is not helpfully refilled with sample data on the next run.
SETUP_MARKER = "initialised"

SAMPLE_TABLES = ("weeks", "staff", "courses", "timetable", "exceptions")


def _add_column_if_missing(conn, table: str, column: str, declaration: str) -> None:
    """The schema is CREATE TABLE IF NOT EXISTS, so it never alters what exists."""
    held = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in held:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


TERM_TABLES = ("timetable", "exceptions")


def _active_term(conn) -> tuple[str, str]:
    held = {r["key"]: r["value"] for r in conn.execute("SELECT * FROM settings")}
    return (held.get("academic_year", ""), held.get("semester", ""))


def _rebuild_weeks_for_terms(conn) -> None:
    """weeks was keyed on the bare week number, which cannot hold two semesters.

    SQLite will not alter a primary key, so the table is rebuilt. Nothing has a
    foreign key to weeks, so this is safe; existing rows are tagged with
    whichever term the settings say was being planned.

    Both halves of an attempt that died partway are recovered from, because a
    rebuild that cannot be retried would wedge the tool on every start from then
    on, and one that gave up on the scratch table would strand a calendar in it.
    """
    tables = {
        r["name"] for r in
        conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(weeks)")}

    if "academic_year" not in columns:
        term = _active_term(conn)
        # Left by an attempt that died after the rename. It is scratch, and the
        # rename below fails while it is there.
        conn.execute("DROP TABLE IF EXISTS weeks_before_terms")
        conn.execute("ALTER TABLE weeks RENAME TO weeks_before_terms")
        conn.executescript(WEEKS_SCHEMA)
        conn.execute(
            "INSERT INTO weeks (academic_year, semester, number, starts, ends, note, is_sample)"
            " SELECT ?, ?, number, starts, ends, note, is_sample FROM weeks_before_terms",
            term,
        )
        conn.execute("DROP TABLE weeks_before_terms")
        return

    # weeks is already the new shape. If an attempt died between the rename and
    # the copy, the real rows are still sitting in the scratch table.
    if "weeks_before_terms" in tables:
        stranded = conn.execute("SELECT COUNT(*) FROM weeks").fetchone()[0] == 0
        if stranded:
            conn.execute(
                "INSERT INTO weeks (academic_year, semester, number, starts, ends, note)"
                " SELECT ?, ?, number, starts, ends, note FROM weeks_before_terms",
                _active_term(conn),
            )
        conn.execute("DROP TABLE weeks_before_terms")


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table in SAMPLE_TABLES:
        _add_column_if_missing(conn, table, "is_sample", "INTEGER NOT NULL DEFAULT 0")

    _rebuild_weeks_for_terms(conn)
    for table in TERM_TABLES:
        fresh = "academic_year" not in {
            r["name"] for r in conn.execute(f"PRAGMA table_info({table})")
        }
        _add_column_if_missing(conn, table, "academic_year", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, table, "semester", "TEXT NOT NULL DEFAULT ''")
        if fresh:
            conn.execute(
                f"UPDATE {table} SET academic_year = ?, semester = ?", _active_term(conn)
            )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_term"
            f" ON {table} (academic_year, semester)"
        )
    conn.commit()


def terms(conn) -> list[tuple[str, str]]:
    """Every term that has a plan, newest looking first."""
    found = {
        (r["academic_year"], r["semester"])
        for r in conn.execute(
            "SELECT academic_year, semester FROM weeks"
            " UNION SELECT academic_year, semester FROM timetable"
        )
    }
    found.add(_active_term(conn))
    return sorted(found, key=lambda t: (t[0], t[1]), reverse=True)


def is_new(conn: sqlite3.Connection) -> bool:
    """Has this database never been set up?

    Not "is the timetable empty": somebody who has cleared the sample data, or
    imported a catalogue before entering any timetable, has an empty timetable
    and does not want it refilled.
    """
    if conn.execute("SELECT 1 FROM settings WHERE key = ?", (SETUP_MARKER,)).fetchone():
        return False
    held = conn.execute(
        "SELECT (SELECT COUNT(*) FROM weeks) + (SELECT COUNT(*) FROM staff)"
        " + (SELECT COUNT(*) FROM courses) + (SELECT COUNT(*) FROM timetable)"
    ).fetchone()[0]
    return held == 0


def mark_setup_done(conn) -> None:
    set_settings(conn, {SETUP_MARKER: "1"})


def has_sample(conn) -> bool:
    return any(
        conn.execute(f"SELECT 1 FROM {table} WHERE is_sample = 1 LIMIT 1").fetchone()
        for table in SAMPLE_TABLES
    )


def mark_all_as_sample(conn) -> None:
    """Everything currently held was put there by seed.load, which runs on a
    cleared database. Anything written afterwards clears its own flag."""
    with conn:
        for table in SAMPLE_TABLES:
            conn.execute(f"UPDATE {table} SET is_sample = 1")


def remove_sample(conn) -> dict:
    """Take out what the app invented, and leave everything else standing."""
    removed = {}
    with conn:
        conn.execute(
            "DELETE FROM assignments WHERE timetable_id IN"
            " (SELECT id FROM timetable WHERE is_sample = 1)"
        )
        conn.execute(
            "DELETE FROM timetable_weeks WHERE timetable_id IN"
            " (SELECT id FROM timetable WHERE is_sample = 1)"
        )
        for table in ("exceptions", "timetable", "courses", "staff", "weeks"):
            cur = conn.execute(f"DELETE FROM {table} WHERE is_sample = 1")
            removed[table] = max(cur.rowcount, 0)

        # The term being planned came with the sample, so it goes with it, unless
        # it has been changed to one the user chose, or something of theirs is
        # still in it. Clearing the term while their rows sit inside it would
        # hide those rows behind a term nobody is looking at.
        settings = get_settings(conn)
        planned = settings.get("sample_planning", "")
        current = f"{settings.get('academic_year', '')}|{settings.get('semester', '')}"
        if planned and planned == current:
            year, semester = planned.split("|", 1)
            survived = conn.execute(
                "SELECT (SELECT COUNT(*) FROM weeks"
                "          WHERE academic_year = ? AND semester = ?)"
                "     + (SELECT COUNT(*) FROM timetable"
                "          WHERE academic_year = ? AND semester = ?)",
                (year, semester, year, semester),
            ).fetchone()[0]
            if not survived:
                conn.execute(
                    "UPDATE settings SET value = ''"
                    " WHERE key IN ('academic_year', 'semester')"
                )
        conn.execute("DELETE FROM settings WHERE key = 'sample_planning'")
    return removed


# ------------------------------------------------------------ reading

def get_weeks(conn, term: tuple[str, str] = ("", "")) -> list[Week]:
    return [
        Week(
            number=r["number"],
            starts=date.fromisoformat(r["starts"]),
            ends=date.fromisoformat(r["ends"]),
            note=r["note"],
        )
        for r in conn.execute(
            "SELECT * FROM weeks WHERE academic_year = ? AND semester = ?"
            " ORDER BY number", term
        )
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


def get_timetable(conn, term: tuple[str, str] = ("", "")) -> list[TimetableRow]:
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
            "SELECT * FROM timetable WHERE academic_year = ? AND semester = ?"
            " ORDER BY course_code, section, id", term
        )
    ]


def get_assignments(conn, term: tuple[str, str] = ("", "")) -> list[Assignment]:
    """Assignments hang off timetable rows, so the row's term scopes them."""
    return [
        Assignment(
            timetable_id=r["timetable_id"], week=r["week"], staff_id=r["staff_id"]
        )
        for r in conn.execute(
            "SELECT a.* FROM assignments a JOIN timetable t ON t.id = a.timetable_id"
            " WHERE t.academic_year = ? AND t.semester = ?"
            " ORDER BY a.timetable_id, a.week", term
        )
    ]


def get_exceptions(conn, term: tuple[str, str] = ("", "")) -> list[ExceptionRow]:
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
            "SELECT * FROM exceptions WHERE academic_year = ? AND semester = ?"
            " ORDER BY week, course_code, section, id", term
        )
    ]


def load_all(conn, term: tuple[str, str] = ("", "")):
    """One term's plan, plus the whole catalogue."""
    return (
        get_weeks(conn, term),
        get_staff(conn),
        get_timetable(conn, term),
        get_exceptions(conn, term),
        get_assignments(conn, term),
        get_courses(conn),
    )


# ------------------------------------------------------------ writing

def replace_weeks(conn, rows: list[dict], term: tuple[str, str] = ("", "")) -> None:
    """Swap in one term's calendar, leaving every other term alone."""
    with conn:
        conn.execute(
            "DELETE FROM weeks WHERE academic_year = ? AND semester = ?", term
        )
        conn.executemany(
            "INSERT INTO weeks (academic_year, semester, number, starts, ends, note)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [
                term + (int(r["number"]), r["starts"], r["ends"], r.get("note") or "")
                for r in rows
            ],
        )


def save_staff(conn, row: dict, original_id: str | None = None) -> str:
    target = row.get("target_minutes")
    target = None if target in ("", None) else int(target)
    with conn:
        if original_id:
            conn.execute(
                "UPDATE staff SET id = ?, name = ?, email = ?, target_minutes = ?,"
                " is_sample = 0 WHERE id = ?",
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


def save_timetable_row(
    conn, row: dict, row_id: int | None = None, term: tuple[str, str] = ("", "")
) -> int:
    values = term + (
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
                "INSERT INTO timetable (academic_year, semester, course_code,"
                " section, day, start, end) VALUES (?, ?, ?, ?, ?, ?, ?)",
                values,
            )
            row_id = cur.lastrowid
        else:
            conn.execute(
                "UPDATE timetable SET academic_year = ?, semester = ?,"
                " course_code = ?, section = ?, day = ?, start = ?, end = ?,"
                " is_sample = 0 WHERE id = ?",
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


def save_exception(
    conn, row: dict, row_id: int | None = None, term: tuple[str, str] = ("", "")
) -> int:
    values = term + (
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
                "INSERT INTO exceptions (academic_year, semester, week, course_code,"
                " section, action, day, start, end, staff_id, note)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )
            return cur.lastrowid
        conn.execute(
            "UPDATE exceptions SET academic_year = ?, semester = ?, week = ?,"
            " course_code = ?, section = ?, action = ?, day = ?, start = ?, end = ?,"
            " staff_id = ?, note = ?, is_sample = 0 WHERE id = ?",
            values + (row_id,),
        )
    return row_id


def delete_exception(conn, row_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM exceptions WHERE id = ?", (row_id,))


# ------------------------------------------------------------ courses

def offerings_in(rows: list[dict]) -> list[tuple[str, str]]:
    """The (year, semester) pairs a file covers."""
    return sorted({
        (str(r.get("academic_year") or ""), str(r.get("semester") or ""))
        for r in rows
    })


def save_courses(conn, rows: list[dict], mode: str = "merge") -> dict:
    """Write catalogue rows, keyed on the whole offering.

    Three ways, because an export is usually one semester of a bigger catalogue:

      merge             update what matches, add the rest, touch nothing else.
                        Importing the same export twice changes nothing.
      replace_offering  refresh only the semesters the file covers, so a course
                        dropped from S2FS goes, and S1FS is left alone.
      replace_all       the deliberate, destructive one.

    An imported row is the user's, never sample data, whatever it replaced.
    """
    before = {c.key for c in get_courses(conn)}
    columns = COURSE_FIELDS + ("is_sample",)
    values = [
        tuple(str(row.get(field) or "") for field in COURSE_FIELDS) + (0,)
        for row in rows
    ]
    placeholders = ", ".join("?" * len(columns))

    with conn:
        if mode == "replace_all":
            conn.execute("DELETE FROM courses")
        elif mode == "replace_offering":
            conn.executemany(
                "DELETE FROM courses WHERE academic_year = ? AND semester = ?",
                offerings_in(rows),
            )
        conn.executemany(
            f"INSERT OR REPLACE INTO courses ({', '.join(columns)})"
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

def replace_timetable(conn, rows: list[dict], term: tuple[str, str] = ("", "")) -> dict:
    """Swap in a freshly imported timetable, keeping staffing where it still fits.

    The timetable is somebody else's document and gets reissued. Staffing is the
    manager's work and should survive that, so assignments are re-attached by
    course, section and week. Anything that no longer has a class under it is
    reported rather than dropped quietly.
    """
    old_rows = get_timetable(conn, term)
    old_assignments = get_assignments(conn, term)
    by_id = {r.id: r for r in old_rows}

    held: dict[tuple[str, str, int], str] = {}
    for a in old_assignments:
        row = by_id.get(a.timetable_id)
        if row is not None:
            held[(row.course_code, row.section, a.week)] = a.staff_id

    doomed = [r.id for r in old_rows]
    with conn:
        conn.executemany("DELETE FROM assignments WHERE timetable_id = ?",
                         [(i,) for i in doomed])
        conn.executemany("DELETE FROM timetable_weeks WHERE timetable_id = ?",
                         [(i,) for i in doomed])
        conn.executemany("DELETE FROM timetable WHERE id = ?", [(i,) for i in doomed])

    kept, dropped = 0, []
    for row in rows:
        new_id = save_timetable_row(conn, row, term=term)
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
