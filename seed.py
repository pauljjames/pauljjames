"""Sample data, so there is something to look at on the first run.

The courses are real, taken from a student management system export. Everything
else is invented: the timetable, because an export carries no days or times, and
the staff, because a course coordinator is not the person in the room. Obviously
made up teachers beside real coordinators is the point rather than an accident.
Dave Carter coordinates 133168; Chen and Dalzell teach it.

It is shaped to show the states the tool exists to distinguish: classes fully
staffed, a semester split between two people, a section nobody covers, a
cancelled week, an added class, and a slot where the obvious candidate is
already busy so the picker has somebody to grey out.

The catalogue is deliberately bigger than the timetable, because a real export
covers a whole school and a manager staffs a slice of it. Two of the five
courses run in the other semester and are not timetabled here.

Everything this module writes is flagged as sample, so Setup can take it out
again without touching anything imported or typed.
"""

from __future__ import annotations

from datetime import date, timedelta

import store

YEAR = "2027"
SEMESTER = "S2FS"
OCCURRENCE = "WLGI"

# Semester two, 2027: twelve teaching weeks from Monday 26 July with a fortnight
# of mid semester break, which puts Labour Day on the Monday of week 12.
FIRST_MONDAY = date(2027, 7, 26)
BREAK_AFTER = 6

WEEK_NOTES = {
    6: "Mid semester break follows, 6 to 17 September",
    12: "Last teaching week. Labour Day, Monday 25 October",
}


def weeks() -> list[tuple[int, str, str, str]]:
    out, monday = [], FIRST_MONDAY
    for number in range(1, 13):
        if number == BREAK_AFTER + 1:
            monday += timedelta(days=14)
        out.append((
            number,
            monday.isoformat(),
            (monday + timedelta(days=6)).isoformat(),
            WEEK_NOTES.get(number, ""),
        ))
        monday += timedelta(days=7)
    return out


# Target contact minutes per week. Not everyone has one.
STAFF = [
    ("ahern", "Ahern, Kate", "k.ahern@example.ac.nz", 480),
    ("brill", "Brill, Sam", "s.brill@example.ac.nz", 480),
    ("chen", "Chen, Wei", "w.chen@example.ac.nz", 360),
    ("dalzell", "Dalzell, Ruth", "r.dalzell@example.ac.nz", 240),
    ("edmond", "Edmond, Tai", "t.edmond@example.ac.nz", None),
    ("fenwick", "Fenwick, Jo", "j.fenwick@example.ac.nz", 480),
]

SCHOOL = "MU00693 - School of Music and Screen Arts"
COLLEGE = "CCA College of Creative Arts"
BCM = "UBCMS-Bachelor of Commercial Music"

# The catalogue, exactly as the export gives it. Coordinators and reviewers are
# accountabilities; nothing in the tool reads them as teaching.
COURSES = [
    {
        "code": "133150", "name": "Live Music Showcases", "semester": "S2FS",
        "programme": "",
        "coordinator": "Andre Ktori", "coordinator_email": "A.Ktori@massey.ac.nz",
        "offering_coordinator": "Dave Carter",
        "offering_coordinator_email": "D.Carter1@massey.ac.nz",
        "grade_reviewer": "", "grade_reviewer_email": "",
    },
    {
        "code": "133154", "name": "Music, People, Places", "semester": "S2FS",
        "programme": BCM,
        "coordinator": "Jon He", "coordinator_email": "J.He1@massey.ac.nz",
        "offering_coordinator": "Jon He",
        "offering_coordinator_email": "J.He1@massey.ac.nz",
        "grade_reviewer": "Dana Cameron", "grade_reviewer_email": "D.Cameron@massey.ac.nz",
    },
    {
        "code": "133167", "name": "Music Entrepreneurship 1", "semester": "S1FS",
        "programme": BCM,
        "coordinator": "Dave Carter", "coordinator_email": "D.Carter1@massey.ac.nz",
        "offering_coordinator": "Dave Carter",
        "offering_coordinator_email": "D.Carter1@massey.ac.nz",
        "grade_reviewer": "Dana Cameron", "grade_reviewer_email": "D.Cameron@massey.ac.nz",
    },
    {
        "code": "133168", "name": "Music Artist Development", "semester": "S2FS",
        "programme": BCM,
        "coordinator": "Dave Carter", "coordinator_email": "D.Carter1@massey.ac.nz",
        "offering_coordinator": "Dave Carter",
        "offering_coordinator_email": "D.Carter1@massey.ac.nz",
        "grade_reviewer": "Dana Cameron", "grade_reviewer_email": "D.Cameron@massey.ac.nz",
    },
    {
        "code": "133175", "name": "Music Practice 1", "semester": "S1FS",
        "programme": BCM,
        "coordinator": "Grayson Gilmour", "coordinator_email": "G.Gilmour@massey.ac.nz",
        "offering_coordinator": "Grayson Gilmour",
        "offering_coordinator_email": "G.Gilmour@massey.ac.nz",
        "grade_reviewer": "", "grade_reviewer_email": "",
    },
]

ALL = list(range(1, 13))
FIRST_HALF = list(range(1, 7))
SECOND_HALF = list(range(7, 13))

# The timetable, which the export does not carry. It names no course and no
# staff: the first comes from the catalogue, the second is the manager's job.
# Only the semester two courses are timetabled.
TIMETABLE = [
    ("133150", "SHOW-A", "Tuesday", "14:00", "17:00", ALL),
    ("133150", "SHOW-B", "Tuesday", "14:00", "17:00", ALL),
    ("133150", "SHOW-C", "Tuesday", "14:00", "17:00", ALL),
    ("133150", "SHOW-D", "Tuesday", "14:00", "17:00", ALL),
    ("133154", "LEC", "Monday", "09:00", "10:00", [7, 8, 9]),
    ("133154", "WS-A", "Monday", "10:00", "12:00", ALL),
    ("133154", "WS-B", "Monday", "10:00", "12:00", ALL),
    ("133154", "TUT-A", "Friday", "09:00", "10:30", ALL),
    ("133154", "TUT-B", "Friday", "11:00", "12:30", ALL),
    ("133168", "SEM", "Wednesday", "11:00", "13:00", ALL),
    ("133168", "STU-A", "Thursday", "09:00", "12:00", ALL),
    ("133168", "STU-B", "Thursday", "09:00", "12:00", ALL),
]

# Who covers what.
#
#   133150 SHOW-D  is deliberately left off: a section nobody covers, so the
#                  dashboard has a real gap to report.
#   133168 STU-A   changes hands at the break, which is a split rather than a
#                  second timetable row.
ASSIGNMENTS = [
    ("133150", "SHOW-A", "ahern", ALL),
    ("133150", "SHOW-B", "brill", ALL),
    ("133150", "SHOW-C", "chen", ALL),
    ("133154", "LEC", "dalzell", [7, 8, 9]),
    ("133154", "WS-A", "edmond", ALL),
    ("133154", "WS-B", "fenwick", ALL),
    ("133154", "TUT-A", "edmond", ALL),
    ("133154", "TUT-B", "edmond", ALL),
    ("133168", "SEM", "dalzell", ALL),
    ("133168", "STU-A", "chen", FIRST_HALF),
    ("133168", "STU-A", "dalzell", SECOND_HALF),
    ("133168", "STU-B", "brill", ALL),
]

# Departures from the timetable. None of them say who teaches.
EXCEPTIONS = [
    {
        "week": 12, "course_code": "133154", "section": "WS-A",
        "action": "Cancel", "note": "Labour Day",
    },
    {
        "week": 12, "course_code": "133154", "section": "WS-B",
        "action": "Cancel", "note": "Labour Day",
    },
    {
        "week": 5, "course_code": "133168", "section": "SEM",
        "action": "Change", "start": "14:00", "end": "16:00",
        "note": "Moved for a visiting speaker",
    },
    {
        "week": 11, "course_code": "133150", "section": "SHOW-A",
        "action": "Add", "day": "Thursday", "start": "13:00", "end": "16:00",
        "staff_id": "ahern", "note": "Extra crit before the showcase",
    },
]


def load(conn) -> None:
    store.replace_weeks(
        conn,
        [
            {"number": n, "starts": s, "ends": e, "note": note}
            for n, s, e, note in weeks()
        ],
    )

    for staff_id, name, email, target in STAFF:
        store.save_staff(
            conn,
            {"id": staff_id, "name": name, "email": email, "target_minutes": target},
        )

    store.save_courses(conn, [
        {
            "academic_year": YEAR,
            "occurrence": OCCURRENCE,
            "college": COLLEGE,
            "department": SCHOOL,
            **course,
        }
        for course in COURSES
    ])

    ids: dict[tuple[str, str], int] = {}
    for code, section, day, start, end, runs in TIMETABLE:
        ids[(code, section)] = store.save_timetable_row(
            conn,
            {
                "course_code": code,
                "section": section,
                "day": day,
                "start": start,
                "end": end,
                "weeks": runs,
            },
        )

    for code, section, staff_id, runs in ASSIGNMENTS:
        store.set_assignment(conn, ids[(code, section)], runs, staff_id)

    for exc in EXCEPTIONS:
        store.save_exception(conn, exc)

    store.mark_all_as_sample(conn)
    store.set_settings(conn, {
        "academic_year": YEAR,
        "semester": SEMESTER,
        "sample_planning": f"{YEAR}|{SEMESTER}",
    })
    store.mark_setup_done(conn)


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
    # An emptied database has still been set up, so nothing refills it later.
    store.mark_setup_done(conn)
