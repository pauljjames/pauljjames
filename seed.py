"""Sample data: the two real courses used to work out how this needs to behave.

Loaded automatically the first time the app runs so there is something to look
at. Clear it from Setup once your own data is in.
"""

from __future__ import annotations

import store

WEEKS = [
    (1, "2026-02-23", "2026-03-01", ""),
    (2, "2026-03-02", "2026-03-08", ""),
    (3, "2026-03-09", "2026-03-15", ""),
    (4, "2026-03-16", "2026-03-22", ""),
    (5, "2026-03-23", "2026-03-29", ""),
    (6, "2026-03-30", "2026-04-05", "Mid semester break follows, 6 to 19 April"),
    (7, "2026-04-20", "2026-04-26", ""),
    (8, "2026-04-27", "2026-05-03", "ANZAC Day observed Monday 27 April"),
    (9, "2026-05-04", "2026-05-10", ""),
    (10, "2026-05-11", "2026-05-17", ""),
    (11, "2026-05-18", "2026-05-24", ""),
    (12, "2026-05-25", "2026-05-31", "Last teaching week"),
]

STAFF = [(f"S{n:02d}", f"Sample, {chr(64 + n)}", "") for n in range(1, 15)]

ALL = list(range(1, 13))

TIMETABLE = [
    ("111.701", "Course One", "A", "S01", "Tuesday", "14:00", "17:00", ALL),
    ("111.701", "Course One", "B", "S02", "Tuesday", "14:00", "17:00", ALL),
    ("111.701", "Course One", "C", "S03", "Tuesday", "14:00", "17:00", ALL),
    ("111.701", "Course One", "D", "S04", "Tuesday", "14:00", "17:00", ALL),
    ("222.702", "Course Two", "LEC", "S05", "Monday", "09:00", "10:00", [7, 8, 9]),
    ("222.702", "Course Two", "WS-A", "S05", "Monday", "09:00", "12:00", ALL),
    ("222.702", "Course Two", "WS-B", "S06", "Monday", "09:00", "12:00", ALL),
    ("222.702", "Course Two", "WS-C", "S01", "Thursday", "09:00", "12:00", ALL),
    ("222.702", "Course Two", "WS-D", "S07", "Thursday", "09:00", "12:00", ALL),
    ("333.703", "Course Three", "A", "S02", "Tuesday", "15:00", "18:00", ALL),
]

EXCEPTIONS = [
    (7, "222.702", "WS-A", "Change", None, None, "10:00", None,
     "Lecture week, workshop shortened"),
    (7, "222.702", "WS-B", "Change", None, None, "10:00", None,
     "Lecture week, workshop shortened"),
    (8, "222.702", "LEC", "Cancel", None, None, None, None,
     "ANZAC Day observed Monday 27 April"),
    (8, "222.702", "WS-A", "Cancel", None, None, None, None,
     "ANZAC Day observed Monday 27 April"),
    (8, "222.702", "WS-B", "Cancel", None, None, None, None,
     "ANZAC Day observed Monday 27 April"),
    (9, "222.702", "WS-A", "Change", None, None, "10:00", None,
     "Lecture week, workshop shortened"),
    (9, "222.702", "WS-B", "Change", None, None, "10:00", None,
     "Lecture week, workshop shortened"),
    (5, "111.701", "C", "Change", "S08", None, None, None,
     "Guest lecturer this week"),
    (12, "111.701", "A", "Add", "S01", "Thursday", "09:00", "12:00",
     "Extra crit session"),
]


def load(conn) -> None:
    store.replace_weeks(
        conn,
        [{"number": n, "starts": s, "ends": e, "note": note} for n, s, e, note in WEEKS],
    )
    for sid, name, email in STAFF:
        store.save_staff(conn, {"id": sid, "name": name, "email": email})
    for code, title, section, staff, day, start, end, weeks in TIMETABLE:
        store.save_timetable_row(
            conn,
            {
                "course_code": code,
                "course_title": title,
                "section": section,
                "staff_id": staff,
                "day": day,
                "start": start,
                "end": end,
                "weeks": weeks,
            },
        )
    for week, code, section, action, staff, day, start, end, note in EXCEPTIONS:
        store.save_exception(
            conn,
            {
                "week": week,
                "course_code": code,
                "section": section,
                "action": action,
                "staff_id": staff,
                "day": day,
                "start": start,
                "end": end,
                "note": note,
            },
        )


def clear(conn) -> None:
    with conn:
        for table in ("timetable_weeks", "timetable", "exceptions", "staff", "weeks"):
            conn.execute(f"DELETE FROM {table}")
