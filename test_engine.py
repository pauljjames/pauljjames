"""Engine tests.

The cases come from two real course outlines: a lecture running in three weeks
only, workshops shortened in those weeks, a public holiday cancellation, a one
week substitution, split semester teaching, and an added crit session.

The tests that matter most are the ones about refusing an assignment, because
that refusal is what the tool is for.
"""

from datetime import date, time, timedelta

import pytest

from engine import (
    Action,
    Assignment,
    Course,
    build_weeks,
    Class,
    ExceptionRow,
    StaffMember,
    Status,
    TimetableRow,
    Week,
    check_assignment,
    classes_for,
    coverage,
    course_names,
    expand,
    find_clashes,
    find_problems,
    group_assignments,
    load_by_staff,
    over_target,
    overlaps,
    reconcile,
    shapes,
    uncovered_rows,
    usual_week,
    validate,
    who_is_free,
)

ALL = frozenset(range(1, 13))


def t(text: str) -> time:
    hh, mm = text.split(":")
    return time(int(hh), int(mm))


def week(n: int) -> Week:
    return Week(number=n, starts=date(2026, 2, 23), ends=date(2026, 3, 1))


def row(id, code, section, day, start, end, weeks=ALL):
    return TimetableRow(
        id=id,
        course_code=code,
        section=section,
        day=day,
        start=t(start),
        end=t(end),
        weeks=frozenset(weeks),
    )


def assign(timetable_id, staff_id, weeks):
    return [Assignment(timetable_id=timetable_id, week=w, staff_id=staff_id) for w in weeks]


# ------------------------------------------------------------ overlap

def test_touching_is_not_overlapping():
    a = Class(1, "A", "", "1", "kate", "Monday", t("09:00"), t("12:00"), Status.SCHEDULED)
    b = Class(1, "B", "", "1", "kate", "Monday", t("12:00"), t("14:00"), Status.SCHEDULED)
    assert not overlaps(a, b)


def test_overlap_needs_the_same_person_day_and_week():
    base = dict(course_title="", status=Status.SCHEDULED)
    a = Class(1, "A", section="1", staff_id="kate", day="Monday",
              start=t("09:00"), end=t("12:00"), **base)
    same = Class(1, "B", section="1", staff_id="kate", day="Monday",
                 start=t("11:00"), end=t("13:00"), **base)
    other_person = Class(1, "B", section="1", staff_id="sam", day="Monday",
                         start=t("11:00"), end=t("13:00"), **base)
    other_day = Class(1, "B", section="1", staff_id="kate", day="Tuesday",
                      start=t("11:00"), end=t("13:00"), **base)
    other_week = Class(2, "B", section="1", staff_id="kate", day="Monday",
                       start=t("11:00"), end=t("13:00"), **base)

    assert overlaps(a, same)
    assert not overlaps(a, other_person)
    assert not overlaps(a, other_day)
    assert not overlaps(a, other_week)


# ------------------------------------------------------------ expansion

def test_a_row_becomes_one_class_per_week_it_runs():
    tt = [row(1, "222.702", "LEC", "Monday", "09:00", "10:00", weeks=[7, 8, 9])]
    classes = expand(tt, [], [])
    assert [c.week for c in classes] == [7, 8, 9]
    assert all(c.status is Status.SCHEDULED for c in classes)


def test_staffing_comes_from_assignments_not_the_timetable():
    tt = [row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=[1, 2, 3])]
    classes = expand(tt, [], assign(1, "kate", [1, 2]))
    assert [(c.week, c.staff_id) for c in classes] == [(1, "kate"), (2, "kate"), (3, None)]


def test_a_class_with_nobody_on_it_is_not_teaching_but_still_runs():
    tt = [row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=[1])]
    only = expand(tt, [], [])[0]
    assert only.runs
    assert not only.covered
    assert not only.is_teaching


def test_a_change_moves_the_class_and_keeps_its_staffing():
    tt = [row(1, "333.703", "LEC", "Wednesday", "11:00", "13:00", weeks=[4, 5])]
    exc = [ExceptionRow(1, 5, "333.703", "LEC", Action.CHANGE, start=t("14:00"), end=t("16:00"))]
    moved = [c for c in expand(tt, exc, assign(1, "ruth", [4, 5])) if c.week == 5][0]
    assert moved.status is Status.CHANGED
    assert (moved.start, moved.end) == (t("14:00"), t("16:00"))
    assert moved.day == "Wednesday"          # untouched fields are inherited
    assert moved.staff_id == "ruth"


def test_a_cancelled_class_keeps_its_person_but_stops_counting():
    tt = [row(1, "222.702", "WS-A", "Monday", "10:00", "12:00", weeks=[7, 8])]
    exc = [ExceptionRow(1, 8, "222.702", "WS-A", Action.CANCEL, note="ANZAC Day")]
    cancelled = [c for c in expand(tt, exc, assign(1, "tai", [7, 8])) if c.week == 8][0]
    assert cancelled.status is Status.CANCELLED
    assert cancelled.staff_id == "tai"       # so the week explains itself
    assert not cancelled.runs
    assert not cancelled.is_teaching
    assert cancelled.minutes == 0


def test_an_added_class_carries_its_own_staff():
    tt = [row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=[11])]
    exc = [ExceptionRow(9, 11, "111.701", "A", Action.ADD, day="Thursday",
                        start=t("13:00"), end=t("16:00"), staff_id="kate")]
    added = [c for c in expand(tt, exc, []) if c.status is Status.ADDED][0]
    assert added.staff_id == "kate"
    assert added.exception_id == 9
    assert added.timetable_row_id is None


def test_a_split_semester_is_two_sets_of_weeks_on_one_row():
    tt = [row(1, "222.702", "WS-C", "Thursday", "09:00", "12:00")]
    assignments = assign(1, "wei", range(1, 7)) + assign(1, "ruth", range(7, 13))
    classes = expand(tt, [], assignments)
    assert {c.staff_id for c in classes if c.week <= 6} == {"wei"}
    assert {c.staff_id for c in classes if c.week >= 7} == {"ruth"}


# ------------------------------------------------------------ the hard block

def test_an_assignment_that_would_double_book_is_refused():
    tt = [
        row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=[1, 2]),
        row(2, "111.701", "B", "Tuesday", "14:00", "17:00", weeks=[1, 2]),
    ]
    classes = expand(tt, [], assign(1, "kate", [1, 2]))
    conflicts = check_assignment(classes, "kate", timetable_id=2, weeks=[1, 2])
    assert [c.week for c in conflicts] == [1, 2]
    assert conflicts[0].existing.label == "111.701 A"
    assert conflicts[0].proposed.label == "111.701 B"


def test_a_free_person_is_not_refused():
    tt = [
        row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=[1, 2]),
        row(2, "111.701", "B", "Tuesday", "14:00", "17:00", weeks=[1, 2]),
    ]
    classes = expand(tt, [], assign(1, "kate", [1, 2]))
    assert check_assignment(classes, "sam", timetable_id=2, weeks=[1, 2]) == []


def test_only_the_weeks_that_actually_overlap_are_refused():
    tt = [
        row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=range(1, 13)),
        row(2, "111.701", "B", "Tuesday", "14:00", "17:00", weeks=range(1, 13)),
    ]
    classes = expand(tt, [], assign(1, "kate", [5, 6]))
    conflicts = check_assignment(classes, "kate", timetable_id=2, weeks=[1, 2, 3, 5])
    assert [c.week for c in conflicts] == [5]


def test_a_person_does_not_conflict_with_the_class_being_offered_to_them():
    """Extending somebody's own class to more weeks is not a clash with itself."""
    tt = [row(1, "222.702", "WS-C", "Thursday", "09:00", "12:00", weeks=range(1, 13))]
    classes = expand(tt, [], assign(1, "wei", range(1, 7)))
    assert check_assignment(classes, "wei", timetable_id=1, weeks=list(range(1, 13))) == []


def test_a_cancelled_week_does_not_block_an_assignment():
    tt = [
        row(1, "222.702", "WS-A", "Monday", "10:00", "12:00", weeks=[8]),
        row(2, "222.702", "WS-B", "Monday", "10:00", "12:00", weeks=[8]),
    ]
    exc = [ExceptionRow(1, 8, "222.702", "WS-A", Action.CANCEL)]
    classes = expand(tt, exc, assign(1, "tai", [8]))
    assert check_assignment(classes, "tai", timetable_id=2, weeks=[8]) == []


def test_a_changed_time_is_what_gets_checked():
    """A class moved out of the way stops blocking; moved into the way, it blocks."""
    tt = [
        row(1, "333.703", "LEC", "Wednesday", "11:00", "13:00", weeks=[5]),
        row(2, "444.704", "SEM", "Wednesday", "11:00", "13:00", weeks=[5]),
    ]
    moved = [ExceptionRow(1, 5, "333.703", "LEC", Action.CHANGE,
                          start=t("14:00"), end=t("16:00"))]

    blocked = expand(tt, [], assign(1, "ruth", [5]))
    assert check_assignment(blocked, "ruth", timetable_id=2, weeks=[5])

    cleared = expand(tt, moved, assign(1, "ruth", [5]))
    assert check_assignment(cleared, "ruth", timetable_id=2, weeks=[5]) == []


def test_an_added_class_blocks_like_any_other():
    tt = [
        row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=[11]),
        row(2, "555.705", "X", "Thursday", "14:00", "16:00", weeks=[11]),
    ]
    exc = [ExceptionRow(9, 11, "111.701", "A", Action.ADD, day="Thursday",
                        start=t("13:00"), end=t("16:00"), staff_id="kate")]
    classes = expand(tt, exc, [])
    conflicts = check_assignment(classes, "kate", timetable_id=2, weeks=[11])
    assert len(conflicts) == 1
    assert conflicts[0].existing.status is Status.ADDED


def test_an_added_class_can_itself_be_checked():
    tt = [row(1, "111.701", "A", "Thursday", "14:00", "17:00", weeks=[11])]
    exc = [ExceptionRow(9, 11, "222.702", "CRIT", Action.ADD, day="Thursday",
                        start=t("13:00"), end=t("16:00"), staff_id="kate")]
    classes = expand(tt, exc, assign(1, "kate", [11]))
    assert check_assignment(classes, "kate", exception_id=9)


def test_unassigning_frees_the_slot():
    tt = [
        row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=[1]),
        row(2, "111.701", "B", "Tuesday", "14:00", "17:00", weeks=[1]),
    ]
    held = expand(tt, [], assign(1, "kate", [1]))
    assert check_assignment(held, "kate", timetable_id=2, weeks=[1])

    freed = expand(tt, [], [])
    assert check_assignment(freed, "kate", timetable_id=2, weeks=[1]) == []


def test_check_with_nothing_to_check_returns_nothing():
    assert check_assignment([], "kate") == []


# ------------------------------------------------------------ availability

def test_who_is_free_reports_the_weeks_somebody_is_busy():
    tt = [row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=[1, 2, 3])]
    classes = expand(tt, [], assign(1, "kate", [1, 3]))
    busy = who_is_free(classes, ["kate", "sam"], "Tuesday", t("14:00"), t("17:00"), [1, 2, 3])
    assert busy == {"kate": [1, 3], "sam": []}


def test_who_is_free_ignores_the_row_being_staffed():
    tt = [row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=[1, 2])]
    classes = expand(tt, [], assign(1, "kate", [1, 2]))
    busy = who_is_free(classes, ["kate"], "Tuesday", t("14:00"), t("17:00"), [1, 2], ignoring=1)
    assert busy == {"kate": []}


# ------------------------------------------------------------ coverage

def test_coverage_counts_class_weeks_that_need_somebody():
    tt = [
        row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=[1, 2]),
        row(2, "111.701", "B", "Tuesday", "14:00", "17:00", weeks=[1, 2]),
    ]
    cover = coverage(expand(tt, [], assign(1, "kate", [1, 2])))
    assert (cover.total, cover.covered, cover.percent) == (4, 2, 50)
    assert {c.label for c in cover.uncovered} == {"111.701 B"}


def test_a_cancelled_week_needs_nobody():
    tt = [row(1, "222.702", "WS-A", "Monday", "10:00", "12:00", weeks=[7, 8])]
    exc = [ExceptionRow(1, 8, "222.702", "WS-A", Action.CANCEL)]
    cover = coverage(expand(tt, exc, []))
    assert cover.total == 1


def test_uncovered_weeks_are_gathered_per_section():
    tt = [row(1, "111.701", "D", "Tuesday", "14:00", "17:00", weeks=range(1, 13))]
    rows = uncovered_rows(expand(tt, [], []))
    assert len(rows) == 1
    assert rows[0]["section"] == "D"
    assert rows[0]["weeks"] == list(range(1, 13))


def test_full_coverage_reports_no_rows():
    tt = [row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=[1])]
    classes = expand(tt, [], assign(1, "kate", [1]))
    assert coverage(classes).percent == 100
    assert uncovered_rows(classes) == []


# ------------------------------------------------------------ display

def test_assignments_group_into_spans_per_row():
    assignments = assign(1, "wei", range(1, 7)) + assign(1, "ruth", range(7, 13))
    grouped = group_assignments(assignments)
    assert grouped[1] == [
        ("wei", tuple(range(1, 7))),
        ("ruth", tuple(range(7, 13))),
    ]


# ------------------------------------------------------------ load

def test_load_adds_up_contact_minutes_per_week():
    tt = [
        row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=[1]),
        row(2, "222.702", "WS-A", "Monday", "10:00", "12:00", weeks=[1]),
    ]
    classes = expand(tt, [], assign(1, "kate", [1]) + assign(2, "kate", [1]))
    assert load_by_staff(classes) == {"kate": {1: 300}}


def test_a_cancelled_class_is_not_load():
    tt = [row(1, "222.702", "WS-A", "Monday", "10:00", "12:00", weeks=[7, 8])]
    exc = [ExceptionRow(1, 8, "222.702", "WS-A", Action.CANCEL)]
    assert load_by_staff(expand(tt, exc, assign(1, "tai", [7, 8]))) == {"tai": {7: 120}}


def test_over_target_names_the_weeks_somebody_is_past_their_target():
    tt = [row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=[1, 2])]
    classes = expand(tt, [], assign(1, "kate", [1, 2]))
    staff = [
        StaffMember("kate", "Kate Ahern", target_minutes=120),
        StaffMember("sam", "Sam Brill", target_minutes=None),
    ]
    assert over_target(staff, classes) == [("kate", 1, 180, 120), ("kate", 2, 180, 120)]


def test_somebody_without_a_target_cannot_be_over_it():
    tt = [row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=[1])]
    classes = expand(tt, [], assign(1, "tai", [1]))
    assert over_target([StaffMember("tai", "Tai Edmond")], classes) == []


def test_a_persons_semester_includes_their_cancelled_weeks():
    tt = [row(1, "222.702", "WS-A", "Monday", "10:00", "12:00", weeks=[7, 8])]
    exc = [ExceptionRow(1, 8, "222.702", "WS-A", Action.CANCEL)]
    mine = classes_for(expand(tt, exc, assign(1, "tai", [7, 8])), "tai")
    assert [c.status for c in mine] == [Status.SCHEDULED, Status.CANCELLED]


# ------------------------------------------------------------ the safety net

def test_clashes_are_still_found_if_the_data_arrives_broken():
    """Assignments are checked on the way in, but an import can still collide."""
    tt = [
        row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=[1, 2]),
        row(2, "333.703", "LEC", "Tuesday", "15:00", "18:00", weeks=[1, 2]),
    ]
    classes = expand(tt, [], assign(1, "kate", [1, 2]) + assign(2, "kate", [1, 2]))
    problems = find_problems(classes)
    assert len(problems) == 1
    assert problems[0].weeks == (1, 2)
    assert problems[0].is_structural


def test_the_shortened_workshop_really_is_what_avoids_the_clash():
    """A guard: remove the exception and the clash must come back.

    Without this the workshop test could pass because clash detection stopped
    working rather than because the timetable is sound.
    """
    tt = [
        row(1, "222.702", "LEC", "Monday", "09:00", "10:00", weeks=[7, 8, 9]),
        row(2, "222.702", "WS-A", "Monday", "09:00", "12:00", weeks=[7, 8, 9]),
    ]
    assignments = assign(1, "tai", [7, 8, 9]) + assign(2, "tai", [7, 8, 9])
    assert find_clashes(expand(tt, [], assignments))

    shortened = [
        ExceptionRow(i, w, "222.702", "WS-A", Action.CHANGE, start=t("10:00"))
        for i, w in enumerate([7, 8, 9], start=1)
    ]
    assert find_clashes(expand(tt, shortened, assignments)) == []


def test_only_the_class_that_collides_is_flagged():
    """A section appearing twice in a week: one copy clashes, the other does not."""
    tt = [
        row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=[11]),
        row(2, "444.704", "SEM", "Thursday", "14:00", "16:00", weeks=[11]),
    ]
    exc = [ExceptionRow(9, 11, "111.701", "A", Action.ADD, day="Thursday",
                        start=t("13:00"), end=t("16:00"), staff_id="kate")]
    classes = expand(tt, exc, assign(1, "kate", [11]) + assign(2, "kate", [11]))
    clashes = find_clashes(classes)
    assert len(clashes) == 1
    involved = {clashes[0].a.status, clashes[0].b.status}
    assert involved == {Status.ADDED, Status.SCHEDULED}
    assert clashes[0].a.day == "Thursday" and clashes[0].b.day == "Thursday"


# ------------------------------------------------------------ validation

def test_a_section_covered_by_two_rows_in_one_week_is_reported():
    weeks = [week(n) for n in (1, 2)]
    tt = [
        row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=[1, 2]),
        row(2, "111.701", "A", "Thursday", "09:00", "12:00", weeks=[2]),
    ]
    issues = validate(weeks, [], tt, [], [])
    assert any("more than one timetable row" in i and "week(s) 2" in i for i in issues)


def test_staffing_inside_an_exception_is_reported():
    weeks = [week(1)]
    tt = [row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=[1])]
    exc = [ExceptionRow(1, 1, "111.701", "A", Action.CHANGE, staff_id="kate")]
    issues = validate(weeks, [StaffMember("kate", "Ahern")], tt, exc, [])
    assert any("staffing does not belong in an exception" in i for i in issues)


def test_an_assignment_to_a_week_the_class_does_not_run_is_reported():
    weeks = [week(n) for n in (1, 2)]
    tt = [row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=[1])]
    issues = validate(weeks, [StaffMember("kate", "Ahern")], tt, [], assign(1, "kate", [2]))
    assert any("does not run in" in i for i in issues)


def test_an_assignment_to_an_unknown_person_is_reported():
    weeks = [week(1)]
    tt = [row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=[1])]
    issues = validate(weeks, [], tt, [], assign(1, "ghost", [1]))
    assert any("not in the staff list" in i for i in issues)


def test_an_added_class_must_say_when_it_meets():
    weeks = [week(1)]
    tt = [row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=[1])]
    exc = [ExceptionRow(1, 1, "111.701", "A", Action.ADD, staff_id="kate")]
    issues = validate(weeks, [StaffMember("kate", "Ahern")], tt, exc, [])
    assert any("needs day, start, end" in i for i in issues)


def test_backwards_times_and_unknown_days_are_reported():
    weeks = [week(1)]
    tt = [row(1, "111.701", "A", "Funday", "17:00", "14:00", weeks=[1])]
    issues = validate(weeks, [], tt, [], [])
    assert any("not a day of the week" in i for i in issues)
    assert any("ends at or before it starts" in i for i in issues)


def test_clean_data_has_nothing_to_report():
    weeks = [week(n) for n in (1, 2)]
    tt = [row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=[1, 2])]
    staff = [StaffMember("kate", "Kate Ahern")]
    assert validate(weeks, staff, tt, [], assign(1, "kate", [1, 2])) == []


# ------------------------------------------------------------ the catalogue

def course(code, name, year="2026", semester="S1FS", occurrence="WLGI"):
    return Course(code=code, name=name, academic_year=year,
                  semester=semester, occurrence=occurrence)


def test_a_class_is_named_by_the_catalogue_not_the_timetable():
    tt = [row(1, "133150", "A", "Tuesday", "14:00", "17:00", weeks=[1])]
    named = expand(tt, [], [], [course("133150", "Live Music Showcases")])
    assert named[0].course_title == "Live Music Showcases"


def test_a_class_whose_course_is_unknown_still_expands_but_has_no_name():
    tt = [row(1, "133150", "A", "Tuesday", "14:00", "17:00", weeks=[1])]
    only = expand(tt, [], [], [])[0]
    assert only.course_title == ""
    assert only.label == "133150 A"


def test_a_course_keeps_its_name_across_offerings():
    both = [course("133150", "Live Music Showcases", semester="S1FS"),
            course("133150", "Live Music Showcases", semester="S2FS")]
    assert course_names(both) == {"133150": "Live Music Showcases"}


def test_a_course_not_in_the_catalogue_is_reported():
    weeks = [week(1)]
    tt = [row(1, "133150", "A", "Tuesday", "14:00", "17:00", weeks=[1])]
    issues = validate(weeks, [], tt, [], [], [course("999999", "Something else")])
    assert any("133150: not in the course list" in i for i in issues)


def test_an_empty_catalogue_does_not_complain_about_every_course():
    weeks = [week(1)]
    tt = [row(1, "133150", "A", "Tuesday", "14:00", "17:00", weeks=[1])]
    assert validate(weeks, [], tt, [], [], []) == []


def test_a_course_from_the_wrong_semester_is_reported():
    weeks = [week(1)]
    tt = [row(1, "133150", "A", "Tuesday", "14:00", "17:00", weeks=[1])]
    issues = validate(weeks, [], tt, [], [],
                      [course("133150", "Live Music Showcases", semester="S2FS")],
                      planning=("2026", "S1FS"))
    assert any("not as an offering in S1FS 2026" in i for i in issues)


def test_the_same_offering_twice_is_reported():
    weeks = [week(1)]
    twice = [course("133150", "One"), course("133150", "One")]
    issues = validate(weeks, [], [], [], [], twice)
    assert any("appears twice" in i for i in issues)


def test_a_course_running_in_both_semesters_is_not_a_duplicate():
    weeks = [week(1)]
    both = [course("133150", "One", semester="S1FS"),
            course("133150", "One", semester="S2FS")]
    assert validate(weeks, [], [], [], [], both) == []


# ------------------------------------------------------------ the usual week

def test_a_person_who_teaches_the_same_week_every_week_has_no_departures():
    tt = [row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=range(1, 13))]
    shape = usual_week(expand(tt, [], assign(1, "kate", range(1, 13))), "kate", list(ALL))
    assert shape.is_settled
    assert shape.usual_weeks == tuple(range(1, 13))
    assert [c.label for c in shape.usual] == ["111.701 A"]
    assert shape.minutes == 180


def test_a_cancelled_week_becomes_a_departure():
    tt = [row(1, "222.702", "WS-A", "Monday", "10:00", "12:00", weeks=range(1, 13))]
    exc = [ExceptionRow(1, 8, "222.702", "WS-A", Action.CANCEL, note="ANZAC Day")]
    shape = usual_week(expand(tt, exc, assign(1, "tai", range(1, 13))), "tai", list(ALL))
    assert not shape.is_settled
    assert len(shape.departures) == 1
    away = shape.departures[0]
    assert away.weeks == (8,)
    assert [c.label for c in away.cancelled] == ["222.702 WS-A"]


def test_an_added_class_becomes_a_departure_that_names_it():
    tt = [row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=range(1, 13))]
    exc = [ExceptionRow(9, 11, "111.701", "A", Action.ADD, day="Thursday",
                        start=t("13:00"), end=t("16:00"), staff_id="kate")]
    shape = usual_week(expand(tt, exc, assign(1, "kate", range(1, 13))), "kate", list(ALL))
    assert shape.usual_weeks == tuple(w for w in range(1, 13) if w != 11)
    assert len(shape.departures) == 1
    assert shape.departures[0].weeks == (11,)
    assert len(shape.departures[0].added) == 1
    assert shape.departures[0].added[0].status is Status.ADDED


def test_a_moved_class_is_reported_as_moved_not_as_two_changes():
    tt = [row(1, "333.703", "LEC", "Wednesday", "11:00", "13:00", weeks=range(1, 13))]
    exc = [ExceptionRow(1, 5, "333.703", "LEC", Action.CHANGE,
                        start=t("14:00"), end=t("16:00"))]
    shape = usual_week(expand(tt, exc, assign(1, "ruth", range(1, 13))), "ruth", list(ALL))
    away = shape.departures[0]
    assert away.weeks == (5,)
    assert away.added == () and away.gone == ()
    assert len(away.moved) == 1
    usually, instead = away.moved[0]
    assert usually.start == t("11:00") and instead.start == t("14:00")


def test_handing_a_class_over_leaves_the_later_weeks_short_of_one():
    """Chen keeps a studio all semester and gives up a workshop at the break."""
    tt = [
        row(1, "111.701", "C", "Tuesday", "14:00", "17:00", weeks=range(1, 13)),
        row(2, "222.702", "WS-C", "Thursday", "09:00", "12:00", weeks=range(1, 13)),
    ]
    assignments = assign(1, "wei", range(1, 13)) + assign(2, "wei", range(1, 7))
    shape = usual_week(expand(tt, [], assignments), "wei", list(ALL))

    # A six/six split is a tie, and the earlier half wins so the answer is stable.
    assert shape.usual_weeks == (1, 2, 3, 4, 5, 6)
    assert len(shape.departures) == 1
    away = shape.departures[0]
    assert away.weeks == (7, 8, 9, 10, 11, 12)
    assert [c.label for c in away.gone] == ["222.702 WS-C"]
    assert away.added == ()


def test_a_week_where_somebody_teaches_nothing_is_a_week_like_any_other():
    tt = [row(1, "222.702", "LEC", "Monday", "09:00", "10:00", weeks=[7, 8, 9])]
    shape = usual_week(expand(tt, [], assign(1, "ruth", [7, 8, 9])), "ruth", list(ALL))
    assert shape.usual == ()                        # nine weeks of nothing wins
    assert shape.usual_weeks == (1, 2, 3, 4, 5, 6, 10, 11, 12)
    assert shape.departures[0].weeks == (7, 8, 9)
    assert [c.label for c in shape.departures[0].added] == ["222.702 LEC"]


def test_somebody_with_no_classes_at_all_has_an_empty_settled_shape():
    shape = usual_week([], "nobody", list(ALL))
    assert shape.usual == ()
    assert shape.is_settled
    assert shape.usual_weeks == tuple(ALL)


def test_the_usual_week_is_read_in_day_and_time_order():
    tt = [
        row(1, "333.703", "TUT", "Friday", "09:00", "10:30", weeks=[1]),
        row(2, "222.702", "WS-A", "Monday", "10:00", "12:00", weeks=[1]),
        row(3, "444.704", "SEM", "Monday", "09:00", "10:00", weeks=[1]),
    ]
    assignments = (assign(1, "tai", [1]) + assign(2, "tai", [1]) + assign(3, "tai", [1]))
    shape = usual_week(expand(tt, [], assignments), "tai", [1])
    assert [c.label for c in shape.usual] == ["444.704 SEM", "222.702 WS-A", "333.703 TUT"]


def test_shapes_covers_everybody_including_people_with_nothing():
    tt = [row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=[1])]
    staff = [StaffMember("kate", "Kate Ahern"), StaffMember("idle", "No Nobody")]
    got = shapes(expand(tt, [], assign(1, "kate", [1])), staff, [1])
    assert [s.staff_id for s in got] == ["kate", "idle"]
    assert got[1].usual == ()


# ------------------------------------------------------------ building a calendar

def test_a_semester_with_no_breaks_is_consecutive_mondays():
    built = build_weeks(date(2027, 7, 26), 4)
    assert [w.number for w in built] == [1, 2, 3, 4]
    assert [w.starts.isoformat() for w in built] == [
        "2027-07-26", "2027-08-02", "2027-08-09", "2027-08-16",
    ]
    assert all(w.ends == w.starts + timedelta(days=6) for w in built)
    assert all(w.note == "" for w in built)


def test_a_break_is_a_gap_between_dates_not_an_extra_week():
    built = build_weeks(date(2027, 7, 26), 12, [(date(2027, 9, 6), date(2027, 9, 17))])
    assert [w.number for w in built] == list(range(1, 13))     # still twelve
    assert built[5].starts.isoformat() == "2027-08-30"          # week 6 before
    assert built[6].starts.isoformat() == "2027-09-20"          # week 7 after
    assert built[5].note == "Break follows, 6 to 17 September"
    assert built[6].note == ""


def test_the_last_teaching_week_lands_where_the_semester_really_ends():
    """Twelve weeks from 26 July 2027 with that break puts Labour Day in week 12."""
    built = build_weeks(date(2027, 7, 26), 12, [(date(2027, 9, 6), date(2027, 9, 17))])
    assert built[-1].starts == date(2027, 10, 25)


def test_two_breaks_are_both_skipped_and_both_named():
    built = build_weeks(date(2027, 7, 26), 6, [
        (date(2027, 8, 9), date(2027, 8, 13)),
        (date(2027, 8, 30), date(2027, 9, 3)),
    ])
    assert [w.starts.isoformat() for w in built] == [
        "2027-07-26", "2027-08-02", "2027-08-16", "2027-08-23",
        "2027-09-06", "2027-09-13",
    ]
    assert built[1].note == "Break follows, 9 to 13 August"
    assert built[3].note == "Break follows, 30 August to 3 September"


def test_a_break_spanning_months_reads_properly():
    built = build_weeks(date(2027, 8, 23), 2, [(date(2027, 8, 30), date(2027, 9, 10))])
    assert built[0].note == "Break follows, 30 August to 10 September"


def test_a_start_that_is_not_a_monday_is_taken_as_that_monday():
    """People give the date teaching starts, not always a Monday."""
    for day in range(26, 32):          # Mon 26 July to Sat 31 July 2027
        assert build_weeks(date(2027, 7, day), 1)[0].starts == date(2027, 7, 26)


def test_a_break_before_teaching_starts_changes_nothing():
    built = build_weeks(date(2027, 7, 26), 2, [(date(2027, 7, 1), date(2027, 7, 9))])
    assert [w.starts.isoformat() for w in built] == ["2027-07-26", "2027-08-02"]


def test_a_semester_of_no_weeks_is_no_weeks():
    assert build_weeks(date(2027, 7, 26), 0) == []


def test_a_backwards_break_is_ignored_rather_than_looping():
    built = build_weeks(date(2027, 7, 26), 2, [(date(2027, 9, 10), date(2027, 9, 1))])
    assert len(built) == 2


# ------------------------------------------------------------ reconciling

def test_reconcile_names_the_rows_behind_an_unknown_course():
    tt = [row(1, "133150", "A", "Tuesday", "14:00", "17:00", weeks=[1]),
          row(2, "133150", "B", "Wednesday", "14:00", "17:00", weeks=[1])]
    found = reconcile(tt, [course("999999", "Something else")])

    # The prose version could only name the code. This can be acted on.
    assert found["unknown"] == [
        {"code": "133150", "row_ids": [1, 2], "sections": ["A", "B"]}]
    assert found["not_offered"] == []


def test_reconcile_separates_the_wrong_semester_from_the_unknown():
    tt = [row(1, "133150", "A", "Tuesday", "14:00", "17:00", weeks=[1])]
    found = reconcile(tt, [course("133150", "Live Music Showcases", semester="S2FS")],
                      planning=("2026", "S1FS"))

    # It is a real course. It is simply not running in what you are planning,
    # which is a different problem with a different fix.
    assert found["unknown"] == []
    assert [f["code"] for f in found["not_offered"]] == ["133150"]


def test_reconcile_reports_a_catalogue_course_nobody_timetabled():
    offered = course("133167", "Sound Design")
    found = reconcile([], [offered], planning=("2026", "S1FS"))
    assert [c["code"] for c in found["untimetabled"]] == ["133167"]


def test_reconcile_says_nothing_when_the_catalogue_is_empty():
    tt = [row(1, "133150", "A", "Tuesday", "14:00", "17:00", weeks=[1])]
    # No catalogue is a tool nobody has imported courses into, not a timetable
    # where every code is wrong.
    assert reconcile(tt, []) == {"unknown": [], "not_offered": [], "untimetabled": []}


def test_reconcile_needs_a_term_before_it_can_judge_an_offering():
    tt = [row(1, "133150", "A", "Tuesday", "14:00", "17:00", weeks=[1])]
    found = reconcile(tt, [course("133150", "Live Music Showcases", semester="S2FS")])
    assert found["not_offered"] == []
    assert found["untimetabled"] == []


def test_the_problems_panel_and_the_reconciler_agree():
    """One rule, two presentations. validate() is prose over reconcile()."""
    weeks = [week(1)]
    tt = [row(1, "133150", "A", "Tuesday", "14:00", "17:00", weeks=[1]),
          row(2, "133154", "LEC", "Monday", "09:00", "10:00", weeks=[1])]
    catalogue = [course("133154", "Music, People, Places")]

    issues = validate(weeks, [], tt, [], [], catalogue, planning=("2026", "S1FS"))
    found = reconcile(tt, catalogue, planning=("2026", "S1FS"))

    assert [f["code"] for f in found["unknown"]] == ["133150"]
    assert any("133150: not in the course list" in i for i in issues)
    # A course that is offered and timetabled is nobody's problem.
    assert found["not_offered"] == [] and found["untimetabled"] == []
