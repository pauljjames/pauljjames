"""Sample data, so there is something to look at on the first run.

It is shaped to show the states the tool exists to distinguish: classes fully
staffed, a semester split between two people, a section nobody covers, a
cancelled week, an added class, and a slot where the obvious candidate is
already busy so the picker has somebody to grey out.

Clear it from Setup once your own timetable is in.
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

# Target contact minutes per week. Not everyone has one.
STAFF = [
    ("ahern", "Ahern, Kate", "k.ahern@example.ac.nz", 480),
    ("brill", "Brill, Sam", "s.brill@example.ac.nz", 480),
    ("chen", "Chen, Wei", "w.chen@example.ac.nz", 360),
    ("dalzell", "Dalzell, Ruth", "r.dalzell@example.ac.nz", 240),
    ("edmond", "Edmond, Tai", "t.edmond@example.ac.nz", None),
    ("fenwick", "Fenwick, Jo", "j.fenwick@example.ac.nz", 480),
]

ALL = list(range(1, 13))
FIRST_HALF = list(range(1, 7))
SECOND_HALF = list(range(7, 13))

# The external timetable. No staffing here: that is the manager's job.
TIMETABLE = [
    ("111.701", "Design Studio", "A", "Tuesday", "14:00", "17:00", ALL),
    ("111.701", "Design Studio", "B", "Tuesday", "14:00", "17:00", ALL),
    ("111.701", "Design Studio", "C", "Tuesday", "14:00", "17:00", ALL),
    ("111.701", "Design Studio", "D", "Tuesday", "14:00", "17:00", ALL),
    ("222.702", "Materials", "LEC", "Monday", "09:00", "10:00", [7, 8, 9]),
    ("222.702", "Materials", "WS-A", "Monday", "10:00", "12:00", ALL),
    ("222.702", "Materials", "WS-B", "Monday", "10:00", "12:00", ALL),
    ("222.702", "Materials", "WS-C", "Thursday", "09:00", "12:00", ALL),
    ("222.702", "Materials", "WS-D", "Thursday", "09:00", "12:00", ALL),
    ("333.703", "History and Theory", "LEC", "Wednesday", "11:00", "13:00", ALL),
    ("333.703", "History and Theory", "TUT-A", "Friday", "09:00", "10:30", ALL),
    ("333.703", "History and Theory", "TUT-B", "Friday", "11:00", "12:30", ALL),
    ("444.704", "Professional Practice", "SEM", "Wednesday", "14:00", "16:00", ALL),
]

# Who covers what, by (course, section) and weeks.
#
#   111.701 D  is deliberately left off: a section nobody covers, so the
#              dashboard has a real gap to report.
#   222.702 WS-C changes hands at the break, which is a split rather than a
#              second timetable row.
ASSIGNMENTS = [
    ("111.701", "A", "ahern", ALL),
    ("111.701", "B", "brill", ALL),
    ("111.701", "C", "chen", ALL),
    ("222.702", "LEC", "dalzell", [7, 8, 9]),
    ("222.702", "WS-A", "edmond", ALL),
    ("222.702", "WS-B", "fenwick", ALL),
    ("222.702", "WS-C", "chen", FIRST_HALF),
    ("222.702", "WS-C", "dalzell", SECOND_HALF),
    ("222.702", "WS-D", "brill", ALL),
    ("333.703", "LEC", "dalzell", ALL),
    ("333.703", "TUT-A", "edmond", ALL),
    ("333.703", "TUT-B", "edmond", ALL),
    ("444.704", "SEM", "ahern", ALL),
]

# Departures from the timetable. None of them say who teaches.
EXCEPTIONS = [
    {
        "week": 8,
        "course_code": "222.702",
        "section": "WS-A",
        "action": "Cancel",
        "note": "ANZAC Day",
    },
    {
        "week": 8,
        "course_code": "222.702",
        "section": "WS-B",
        "action": "Cancel",
        "note": "ANZAC Day",
    },
    {
        "week": 5,
        "course_code": "333.703",
        "section": "LEC",
        "action": "Change",
        "start": "14:00",
        "end": "16:00",
        "note": "Moved for a visiting speaker",
    },
    {
        "week": 11,
        "course_code": "111.701",
        "section": "A",
        "action": "Add",
        "day": "Thursday",
        "start": "13:00",
        "end": "16:00",
        "staff_id": "ahern",
        "note": "Extra crit before hand in",
    },
]


def load(conn) -> None:
    store.replace_weeks(
        conn,
        [
            {"number": n, "starts": s, "ends": e, "note": note}
            for n, s, e, note in WEEKS
        ],
    )

    for staff_id, name, email, target in STAFF:
        store.save_staff(
            conn,
            {"id": staff_id, "name": name, "email": email, "target_minutes": target},
        )

    ids: dict[tuple[str, str], int] = {}
    for code, title, section, day, start, end, weeks in TIMETABLE:
        ids[(code, section)] = store.save_timetable_row(
            conn,
            {
                "course_code": code,
                "course_title": title,
                "section": section,
                "day": day,
                "start": start,
                "end": end,
                "weeks": weeks,
            },
        )

    for code, section, staff_id, weeks in ASSIGNMENTS:
        store.set_assignment(conn, ids[(code, section)], weeks, staff_id)

    for exc in EXCEPTIONS:
        store.save_exception(conn, exc)


def clear(conn) -> None:
    with conn:
        for table in (
            "assignments",
            "exceptions",
            "timetable_weeks",
            "timetable",
            "staff",
            "weeks",
        ):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('timetable', 'exceptions')")
