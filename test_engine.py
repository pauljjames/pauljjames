"""Engine tests.

The cases come from two real course outlines: a lecture running in three weeks
only, workshops shortened in those weeks, a public holiday cancellation, a one
week substitution, split semester teaching, and an added crit session.

The tests that matter most are the ones about refusing an assignment, because
that refusal is what the tool is for.
"""

from datetime import date, time

import pytest

from engine import (
    Action,
    Assignment,
    Class,
    ExceptionRow,
    StaffMember,
    Status,
    TimetableRow,
    Week,
    check_assignment,
    classes_for,
    coverage,
    expand,
    find_clashes,
    find_problems,
    group_assignments,
    load_by_staff,
    over_target,
    overlaps,
    uncovered_rows,
    validate,
    who_is_free,
)

ALL = frozenset(range(1, 13))


def t(text: str) -> time:
    hh, mm = text.split(":")
    return time(int(hh), int(mm))


def week(n: int) -> Week:
    return Week(number=n, starts=date(2026, 2, 23), ends=date(2026, 3, 1))


def row(id, code, section, day, start, end, weeks=ALL, title="Course"):
    return TimetableRow(
        id=id,
        course_code=code,
        course_title=title,
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
        StaffMember("kate", "Ahern, Kate", target_minutes=120),
        StaffMember("sam", "Brill, Sam", target_minutes=None),
    ]
    assert over_target(staff, classes) == [("kate", 1, 180, 120), ("kate", 2, 180, 120)]


def test_somebody_without_a_target_cannot_be_over_it():
    tt = [row(1, "111.701", "A", "Tuesday", "14:00", "17:00", weeks=[1])]
    classes = expand(tt, [], assign(1, "tai", [1]))
    assert over_target([StaffMember("tai", "Edmond, Tai")], classes) == []


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
    staff = [StaffMember("kate", "Ahern, Kate")]
    assert validate(weeks, staff, tt, [], assign(1, "kate", [1, 2])) == []
