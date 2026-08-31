"""Tests for the timetable engine.

Every case here came out of the spreadsheet prototype and was checked against
two real course outlines, so these are the behaviours the tool is known to need
rather than ones invented to suit the code.
"""

from datetime import date, time

import pytest

from engine import (
    Action,
    Class,
    ExceptionRow,
    StaffMember,
    Status,
    TimetableRow,
    Week,
    classes_for,
    expand,
    find_clashes,
    find_problems,
    load_by_staff,
    who_is_free,
    overlaps,
    validate,
)

ALL_WEEKS = frozenset(range(1, 13))


# --------------------------------------------------------------- fixtures


@pytest.fixture
def weeks():
    starts = [
        date(2026, 2, 23), date(2026, 3, 2), date(2026, 3, 9), date(2026, 3, 16),
        date(2026, 3, 23), date(2026, 3, 30), date(2026, 4, 20), date(2026, 4, 27),
        date(2026, 5, 4), date(2026, 5, 11), date(2026, 5, 18), date(2026, 5, 25),
    ]
    return [Week(number=i + 1, starts=d, ends=d) for i, d in enumerate(starts)]


@pytest.fixture
def staff():
    return [StaffMember(id=f"S{n:02d}", name=f"Sample {n}") for n in range(1, 15)]


@pytest.fixture
def timetable():
    """The two real courses, plus a third that collides with the first."""
    return [
        TimetableRow(1, "111.701", "Course One", "A", "S01", "Tuesday",
                     time(14, 0), time(17, 0), ALL_WEEKS),
        TimetableRow(2, "111.701", "Course One", "B", "S02", "Tuesday",
                     time(14, 0), time(17, 0), ALL_WEEKS),
        TimetableRow(3, "111.701", "Course One", "C", "S03", "Tuesday",
                     time(14, 0), time(17, 0), ALL_WEEKS),
        TimetableRow(4, "222.702", "Course Two", "LEC", "S05", "Monday",
                     time(9, 0), time(10, 0), frozenset({7, 8, 9})),
        TimetableRow(5, "222.702", "Course Two", "WS-A", "S05", "Monday",
                     time(9, 0), time(12, 0), ALL_WEEKS),
        TimetableRow(6, "222.702", "Course Two", "WS-C", "S01", "Thursday",
                     time(9, 0), time(12, 0), ALL_WEEKS),
        TimetableRow(7, "333.703", "Course Three", "A", "S02", "Tuesday",
                     time(15, 0), time(18, 0), ALL_WEEKS),
    ]


@pytest.fixture
def exceptions():
    return [
        # Workshops shorten in lecture weeks so the lecturer is not double booked.
        ExceptionRow(1, 7, "222.702", "WS-A", Action.CHANGE, start=time(10, 0),
                     note="Lecture week"),
        ExceptionRow(2, 9, "222.702", "WS-A", Action.CHANGE, start=time(10, 0),
                     note="Lecture week"),
        # ANZAC Day observed on the Monday of week 8.
        ExceptionRow(3, 8, "222.702", "LEC", Action.CANCEL, note="ANZAC Day"),
        ExceptionRow(4, 8, "222.702", "WS-A", Action.CANCEL, note="ANZAC Day"),
        # A guest takes one week only.
        ExceptionRow(5, 5, "111.701", "C", Action.CHANGE, staff_id="S08",
                     note="Guest lecturer"),
        # An extra crit session with no timetable row behind it.
        ExceptionRow(6, 12, "111.701", "A", Action.ADD, staff_id="S01",
                     day="Thursday", start=time(9, 0), end=time(12, 0),
                     note="Extra crit"),
    ]


@pytest.fixture
def classes(timetable, exceptions):
    return expand(timetable, exceptions)


def one(classes, week, code, section):
    found = [c for c in classes if c.week == week and c.course_code == code
             and c.section == section]
    assert len(found) == 1, f"expected exactly one {code} {section} in week {week}"
    return found[0]


# --------------------------------------------------------------- overlap rule


def klass(**kw):
    base = dict(week=1, course_code="X", course_title="", section="A", staff_id="S01",
                day="Monday", start=time(9, 0), end=time(12, 0),
                status=Status.SCHEDULED)
    return Class(**{**base, **kw})


def test_touching_is_not_a_clash():
    a = klass(start=time(9, 0), end=time(12, 0))
    b = klass(section="B", start=time(12, 0), end=time(15, 0))
    assert not overlaps(a, b)


def test_partial_overlap_is_a_clash():
    a = klass(start=time(9, 0), end=time(12, 0))
    b = klass(section="B", start=time(11, 0), end=time(14, 0))
    assert overlaps(a, b)


def test_different_people_never_clash():
    a = klass(staff_id="S01")
    b = klass(staff_id="S02", section="B")
    assert not overlaps(a, b)


def test_different_weeks_never_clash():
    a = klass(week=1)
    b = klass(week=2, section="B")
    assert not overlaps(a, b)


def test_cancelled_classes_never_clash():
    a = klass()
    b = klass(section="B", status=Status.CANCELLED)
    assert not overlaps(a, b)


def test_unstaffed_classes_never_clash():
    a = klass(staff_id=None)
    b = klass(section="B", staff_id=None)
    assert not overlaps(a, b)


# --------------------------------------------------------------- expansion


def test_a_row_produces_one_class_per_week_it_runs(classes):
    lec = [c for c in classes if c.section == "LEC"]
    assert sorted(c.week for c in lec) == [7, 8, 9]


def test_untouched_weeks_are_scheduled(classes):
    assert one(classes, 1, "222.702", "WS-A").status is Status.SCHEDULED


def test_change_overrides_only_what_it_supplies(classes):
    week5 = one(classes, 5, "111.701", "C")
    assert week5.staff_id == "S08"          # supplied by the exception
    assert week5.day == "Tuesday"           # inherited
    assert week5.start == time(14, 0)       # inherited
    assert week5.status is Status.CHANGED


def test_cancel_removes_the_class_from_the_reckoning(classes):
    cancelled = one(classes, 8, "222.702", "WS-A")
    assert cancelled.status is Status.CANCELLED
    assert cancelled.staff_id is None
    assert cancelled.minutes == 0
    assert not cancelled.is_teaching


def test_cancel_keeps_the_class_visible(classes):
    """A cancelled class must not vanish, or nobody can see why a week is empty."""
    assert one(classes, 8, "222.702", "LEC").course_code == "222.702"


def test_add_creates_a_class_with_no_timetable_row(classes):
    added = [c for c in classes if c.status is Status.ADDED]
    assert len(added) == 1
    assert added[0].week == 12
    assert added[0].timetable_row_id is None
    assert added[0].minutes == 180


# --------------------------------------------------------------- the real cases


def test_shortened_workshop_prevents_a_false_clash(classes):
    """The lecturer runs the lecture and a workshop back to back in week 7."""
    lecture = one(classes, 7, "222.702", "LEC")
    workshop = one(classes, 7, "222.702", "WS-A")
    assert lecture.staff_id == workshop.staff_id == "S05"
    assert lecture.end == time(10, 0)
    assert workshop.start == time(10, 0)
    assert not overlaps(lecture, workshop)


def test_without_the_shortening_it_would_clash(timetable):
    """Guards the test above: the exception is doing real work."""
    unshortened = expand(timetable, [])
    lecture = one(unshortened, 7, "222.702", "LEC")
    workshop = one(unshortened, 7, "222.702", "WS-A")
    assert overlaps(lecture, workshop)


def test_public_holiday_empties_the_week(classes):
    assert classes_for(classes, "S05", week=8) == []


def test_split_semester_teaching_needs_no_exceptions(staff):
    """Staff A for weeks 1 to 6, Staff B for 7 to 12, as two timetable rows."""
    split = [
        TimetableRow(1, "444.704", "Course Four", "A", "S03", "Wednesday",
                     time(9, 0), time(12, 0), frozenset(range(1, 7))),
        TimetableRow(2, "444.704", "Course Four", "A", "S09", "Wednesday",
                     time(9, 0), time(12, 0), frozenset(range(7, 13))),
    ]
    result = expand(split, [])
    assert len(result) == 12
    assert one(result, 6, "444.704", "A").staff_id == "S03"
    assert one(result, 7, "444.704", "A").staff_id == "S09"
    assert find_clashes(result) == []


# --------------------------------------------------------------- clashes


def test_the_structural_clash_recurs_every_week(classes):
    clashes = [c for c in find_clashes(classes) if c.staff_id == "S02"]
    assert sorted(c.week for c in clashes) == list(range(1, 13))


def test_problems_collapse_recurring_clashes_into_one_row(classes):
    problems = find_problems(classes)
    assert len(problems) == 2

    structural = problems[0]
    assert structural.staff_id == "S02"
    assert structural.weeks == tuple(range(1, 13))
    assert structural.is_structural

    one_off = problems[1]
    assert one_off.staff_id == "S01"
    assert one_off.weeks == (12,)
    assert not one_off.is_structural


def test_an_added_class_can_cause_a_clash(classes):
    """The extra crit collides with a Thursday workshop the same person runs."""
    week12 = [c for c in find_clashes(classes) if c.week == 12 and c.staff_id == "S01"]
    assert len(week12) == 1
    labels = {week12[0].a.label, week12[0].b.label}
    assert labels == {"111.701 A", "222.702 WS-C"}


# --------------------------------------------------------------- load


def test_load_counts_teaching_minutes_per_week(classes):
    load = load_by_staff(classes)
    assert load["S05"][1] == 180            # workshop only
    assert load["S05"][7] == 60 + 120       # lecture plus shortened workshop
    assert 8 not in load["S05"]             # ANZAC Day


def test_load_follows_a_guest_lecturer(classes):
    load = load_by_staff(classes)
    assert load["S08"] == {5: 180}
    assert 5 not in load["S03"]


# --------------------------------------------------------------- validation


def test_clean_data_produces_no_issues(weeks, staff, timetable, exceptions):
    assert validate(weeks, staff, timetable, exceptions) == []


def test_the_failure_that_broke_the_spreadsheet_is_caught(weeks, staff):
    """Two timetable rows covering the same section in the same week."""
    overlapping = [
        TimetableRow(1, "444.704", "Course Four", "A", "S03", "Wednesday",
                     time(9, 0), time(12, 0), frozenset(range(1, 8))),
        TimetableRow(2, "444.704", "Course Four", "A", "S09", "Wednesday",
                     time(9, 0), time(12, 0), frozenset(range(7, 13))),
    ]
    issues = validate(weeks, staff, overlapping, [])
    assert any("week(s) 7" in i for i in issues)


def test_unknown_staff_is_caught(weeks, staff, timetable):
    broken = timetable + [
        TimetableRow(99, "555.705", "Course Five", "A", "S99", "Friday",
                     time(9, 0), time(12, 0), ALL_WEEKS)
    ]
    assert any("S99" in i for i in validate(weeks, staff, broken, []))


def test_exception_for_a_week_the_section_does_not_run_is_caught(weeks, staff, timetable):
    stray = [ExceptionRow(1, 3, "222.702", "LEC", Action.CANCEL)]
    issues = validate(weeks, staff, timetable, stray)
    assert any("does not run in week 3" in i for i in issues)


def test_exception_for_an_unknown_section_is_caught(weeks, staff, timetable):
    stray = [ExceptionRow(1, 3, "999.999", "Z", Action.CANCEL)]
    issues = validate(weeks, staff, timetable, stray)
    assert any("no timetable row" in i for i in issues)


def test_incomplete_added_class_is_caught(weeks, staff, timetable):
    thin = [ExceptionRow(1, 4, "111.701", "A", Action.ADD, staff_id="S01")]
    issues = validate(weeks, staff, timetable, thin)
    assert any("needs day, start, end" in i for i in issues)


def test_backwards_times_are_caught(weeks, staff):
    backwards = [
        TimetableRow(1, "666.706", "Course Six", "A", "S01", "Monday",
                     time(15, 0), time(12, 0), ALL_WEEKS)
    ]
    assert any("before it starts" in i for i in validate(weeks, staff, backwards, []))


def test_week_outside_the_calendar_is_caught(weeks, staff):
    too_far = [
        TimetableRow(1, "777.707", "Course Seven", "A", "S01", "Monday",
                     time(9, 0), time(12, 0), frozenset({1, 99}))
    ]
    assert any("week 99" in i for i in validate(weeks, staff, too_far, []))


# --------------------------------------------------------------- who is free


def test_who_is_free_reports_busy_weeks(classes, staff):
    """Offering the Tuesday afternoon slot to everyone: who could take it?"""
    ids = [s.id for s in staff]
    busy = who_is_free(classes, ids, "Tuesday", time(14, 0), time(17, 0),
                       list(range(1, 13)))
    assert busy["S01"] == list(range(1, 13))   # already teaching then
    assert busy["S10"] == []                   # teaching nothing at all
    assert busy["S03"] == [w for w in range(1, 13) if w != 5]  # away in week 5


def test_who_is_free_ignores_the_class_being_handed_over(classes, staff):
    """S01 teaches 111.701 A on Tuesdays. Asked whether they could take that
    very class, the answer must not be 'no, they are teaching it'."""
    ids = [s.id for s in staff]
    without = who_is_free(classes, ids, "Tuesday", time(14, 0), time(17, 0),
                          list(range(1, 13)), ignoring=("111.701", "A"))
    assert without["S01"] == []


def test_who_is_free_ignores_other_days(classes, staff):
    ids = [s.id for s in staff]
    busy = who_is_free(classes, ids, "Friday", time(9, 0), time(12, 0),
                       list(range(1, 13)))
    assert all(weeks == [] for weeks in busy.values())


def test_who_is_free_treats_a_cancelled_week_as_free(classes, staff):
    """S05's Monday morning is cancelled in week 8, so they are free then."""
    ids = [s.id for s in staff]
    busy = who_is_free(classes, ids, "Monday", time(9, 0), time(12, 0),
                       list(range(1, 13)))
    assert 8 not in busy["S05"]
