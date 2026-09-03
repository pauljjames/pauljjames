"""Sample data, so there is something to look at on the first run.

It is shaped to show the states the tool exists to distinguish: classes fully
staffed, a semester split between two people, a section nobody covers, a
cancelled week, an added class, and a slot where the obvious candidate is
already busy so the picker has somebody to grey out.

The catalogue is deliberately bigger than the timetable, because a real export
covers a whole school and a manager staffs a slice of it.

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

YEAR = "2026"
SEMESTER = "S1FS"

# The catalogue, as it would arrive from the student management system. The
# coordinators here are accountabilities, not teaching: nothing reads them as
# staffing. The last two are not timetabled at all, which is normal.
COURSES = [
    ("111.701", "Design Studio", SEMESTER, "Ktori, Andre", "Carter, Dave"),
    ("222.702", "Materials", SEMESTER, "Carter, Dave", "Carter, Dave"),
    ("333.703", "History and Theory", SEMESTER, "He, Jon", "He, Jon"),
    ("444.704", "Professional Practice", SEMESTER, "Gilmour, Grayson", "Carter, Dave"),
    ("555.705", "Digital Fabrication", SEMESTER, "Cameron, Dana", "Cameron, Dana"),
    ("666.706", "Sound Studies", "S2FS", "He, Jon", "He, Jon"),
]

# The external timetable. It names no course and no staff: the first comes from
# the catalogue, the second is the manager's job.
TIMETABLE = [
    ("111.701", "A", "Tuesday", "14:00", "17:00", ALL),
    ("111.701", "B", "Tuesday", "14:00", "17:00", ALL),
    ("111.701", "C", "Tuesday", "14:00", "17:00", ALL),
    ("111.701", "D", "Tuesday", "14:00", "17:00", ALL),
    ("222.702", "LEC", "Monday", "09:00", "10:00", [7, 8, 9]),
    ("222.702", "WS-A", "Monday", "10:00", "12:00", ALL),
    ("222.702", "WS-B", "Monday", "10:00", "12:00", ALL),
    ("222.702", "WS-C", "Thursday", "09:00", "12:00", ALL),
    ("222.702", "WS-D", "Thursday", "09:00", "12:00", ALL),
    ("333.703", "LEC", "Wednesday", "11:00", "13:00", ALL),
    ("333.703", "TUT-A", "Friday", "09:00", "10:30", ALL),
    ("333.703", "TUT-B", "Friday", "11:00", "12:30", ALL),
    ("444.704", "SEM", "Wednesday", "14:00", "16:00", ALL),
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


def _email(name: str) -> str:
    """Surname, First becomes F.Surname@example.ac.nz."""
    if not name:
        return ""
    surname, _, first = name.partition(",")
    initial = first.strip()[:1]
    return f"{initial}.{surname.strip()}@example.ac.nz".lower()


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

    store.save_courses(conn, [
        {
            "code": code,
            "name": name,
            "academic_year": YEAR,
            "semester": semester,
            "occurrence": "WLGI",
            "college": "CCA College of Creative Arts",
            "programme": "UBDES-Bachelor of Design",
            "coordinator": coordinator,
            "coordinator_email": _email(coordinator),
            "offering_coordinator": offering,
            "offering_coordinator_email": _email(offering),
            "grade_reviewer": "",
            "grade_reviewer_email": "",
            "department": "SD00123 - School of Design",
        }
        for code, name, semester, coordinator, offering in COURSES
    ])

    store.set_settings(conn, {"academic_year": YEAR, "semester": SEMESTER})

    ids: dict[tuple[str, str], int] = {}
    for code, section, day, start, end, weeks in TIMETABLE:
        ids[(code, section)] = store.save_timetable_row(
            conn,
            {
                "course_code": code,
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
            "courses",
            "settings",
            "exceptions",
            "timetable_weeks",
            "timetable",
            "staff",
            "weeks",
        ):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('timetable', 'exceptions')")
