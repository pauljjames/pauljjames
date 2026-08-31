"""Timetable expansion, clash detection and teaching load.

Pure domain logic. This module knows nothing about databases, HTTP, files or
user interfaces, and it must stay that way. Everything here is a plain function
over plain data, so it can be tested without spinning anything up and reused
whichever way the tool is eventually delivered.

The model, in short:

  Week          one teaching week, numbered 1..n, with real dates attached
  StaffMember   someone whose availability is being tracked
  TimetableRow  a course and section, its usual staff member, day and time,
                and the set of weeks it runs
  ExceptionRow  a departure from the timetable in a single week
  Class         one course and section actually meeting in one week
  Clash         two classes the same person cannot both be at

A TimetableRow expands into one Class per week it runs. Exceptions are then
applied on top: CHANGE overrides only the fields it supplies, CANCEL removes
the class from clash detection, and ADD creates a class with no timetable row
behind it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, time
from enum import Enum
from itertools import combinations

WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


class Action(str, Enum):
    CHANGE = "Change"
    CANCEL = "Cancel"
    ADD = "Add"


class Status(str, Enum):
    SCHEDULED = "Scheduled"
    CHANGED = "Changed"
    CANCELLED = "Cancelled"
    ADDED = "Added"


@dataclass(frozen=True)
class Week:
    number: int
    starts: date
    ends: date
    note: str = ""


@dataclass(frozen=True)
class StaffMember:
    id: str
    name: str
    email: str = ""


@dataclass(frozen=True)
class TimetableRow:
    id: int
    course_code: str
    course_title: str
    section: str
    staff_id: str | None
    day: str
    start: time
    end: time
    weeks: frozenset[int]

    @property
    def key(self) -> tuple[str, str]:
        return (self.course_code, self.section)


@dataclass(frozen=True)
class ExceptionRow:
    id: int
    week: int
    course_code: str
    section: str
    action: Action
    staff_id: str | None = None
    day: str | None = None
    start: time | None = None
    end: time | None = None
    note: str = ""

    @property
    def key(self) -> tuple[int, str, str]:
        return (self.week, self.course_code, self.section)


@dataclass(frozen=True)
class Class:
    week: int
    course_code: str
    course_title: str
    section: str
    staff_id: str | None
    day: str | None
    start: time | None
    end: time | None
    status: Status
    timetable_row_id: int | None = None
    exception_id: int | None = None

    @property
    def label(self) -> str:
        return f"{self.course_code} {self.section}"

    @property
    def is_teaching(self) -> bool:
        """Does this class occupy someone's time?"""
        return (
            self.status is not Status.CANCELLED
            and self.staff_id is not None
            and self.start is not None
            and self.end is not None
        )

    @property
    def minutes(self) -> int:
        if self.start is None or self.end is None or self.status is Status.CANCELLED:
            return 0
        return _minutes(self.end) - _minutes(self.start)


@dataclass(frozen=True)
class Clash:
    week: int
    staff_id: str
    a: Class
    b: Class

    @property
    def pair_key(self) -> tuple[str, str, str]:
        """Identifies the clash independently of week or which side is first.

        Two classes colliding in ten weeks is one problem, not ten. This key is
        what lets the interface say so.
        """
        first, second = sorted([self.a.label, self.b.label])
        return (self.staff_id, first, second)


@dataclass(frozen=True)
class Problem:
    """A distinct clash, and every week it happens in."""

    staff_id: str
    a: Class
    b: Class
    weeks: tuple[int, ...]

    @property
    def is_structural(self) -> bool:
        return len(self.weeks) > 1


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def overlaps(a: Class, b: Class) -> bool:
    """True when two classes collide.

    Touching is not overlapping: a class ending at 12:00 does not clash with one
    starting at 12:00.
    """
    if not (a.is_teaching and b.is_teaching):
        return False
    if a.week != b.week or a.day != b.day or a.staff_id != b.staff_id:
        return False
    return _minutes(a.start) < _minutes(b.end) and _minutes(b.start) < _minutes(a.end)


def expand(
    timetable: list[TimetableRow],
    exceptions: list[ExceptionRow],
) -> list[Class]:
    """Build every class in every week from the timetable plus its exceptions."""
    overrides: dict[tuple[int, str, str], ExceptionRow] = {}
    for exc in exceptions:
        if exc.action is Action.ADD:
            continue
        overrides.setdefault(exc.key, exc)

    classes: list[Class] = []

    for row in timetable:
        for week in sorted(row.weeks):
            exc = overrides.get((week, row.course_code, row.section))
            if exc is None:
                classes.append(
                    Class(
                        week=week,
                        course_code=row.course_code,
                        course_title=row.course_title,
                        section=row.section,
                        staff_id=row.staff_id,
                        day=row.day,
                        start=row.start,
                        end=row.end,
                        status=Status.SCHEDULED,
                        timetable_row_id=row.id,
                    )
                )
                continue

            base = Class(
                week=week,
                course_code=row.course_code,
                course_title=row.course_title,
                section=row.section,
                staff_id=row.staff_id,
                day=row.day,
                start=row.start,
                end=row.end,
                status=Status.CHANGED,
                timetable_row_id=row.id,
                exception_id=exc.id,
            )

            if exc.action is Action.CANCEL:
                classes.append(
                    replace(
                        base,
                        status=Status.CANCELLED,
                        staff_id=None,
                        day=None,
                        start=None,
                        end=None,
                    )
                )
                continue

            # CHANGE: only the fields the exception supplies are overridden.
            classes.append(
                replace(
                    base,
                    staff_id=exc.staff_id if exc.staff_id is not None else row.staff_id,
                    day=exc.day if exc.day is not None else row.day,
                    start=exc.start if exc.start is not None else row.start,
                    end=exc.end if exc.end is not None else row.end,
                )
            )

    titles = {r.course_code: r.course_title for r in timetable}
    for exc in exceptions:
        if exc.action is not Action.ADD:
            continue
        classes.append(
            Class(
                week=exc.week,
                course_code=exc.course_code,
                course_title=titles.get(exc.course_code, ""),
                section=exc.section,
                staff_id=exc.staff_id,
                day=exc.day,
                start=exc.start,
                end=exc.end,
                status=Status.ADDED,
                exception_id=exc.id,
            )
        )

    classes.sort(key=lambda c: (c.week, c.course_code, c.section))
    return classes


def find_clashes(classes: list[Class]) -> list[Clash]:
    """Every pair of classes the same person cannot both attend."""
    by_staff_week: dict[tuple[str, int], list[Class]] = {}
    for c in classes:
        if not c.is_teaching:
            continue
        by_staff_week.setdefault((c.staff_id, c.week), []).append(c)

    clashes: list[Clash] = []
    for (staff_id, week), group in by_staff_week.items():
        for a, b in combinations(group, 2):
            if overlaps(a, b):
                first, second = sorted([a, b], key=lambda c: (c.course_code, c.section))
                clashes.append(Clash(week=week, staff_id=staff_id, a=first, b=second))

    clashes.sort(key=lambda x: (x.week, x.staff_id, x.a.label))
    return clashes


def find_problems(classes: list[Class]) -> list[Problem]:
    """Clashes grouped into distinct problems, with the weeks each occurs in.

    This is what a person should be shown. One recurring collision is one row
    with twelve weeks marked, not twelve rows.
    """
    grouped: dict[tuple[str, str, str], list[Clash]] = {}
    for clash in find_clashes(classes):
        grouped.setdefault(clash.pair_key, []).append(clash)

    problems = [
        Problem(
            staff_id=items[0].staff_id,
            a=items[0].a,
            b=items[0].b,
            weeks=tuple(sorted({c.week for c in items})),
        )
        for items in grouped.values()
    ]
    problems.sort(key=lambda p: (-len(p.weeks), p.staff_id, p.a.label))
    return problems


def who_is_free(
    classes: list[Class],
    staff_ids: list[str],
    day: str,
    start: time,
    end: time,
    weeks: list[int],
    ignoring: tuple[str, str] | None = None,
) -> dict[str, list[int]]:
    """Which weeks each person is already busy in, for a proposed slot.

    Answers the question a person actually has when a clash appears: if not
    them, then who? An empty list means that person is free for every week
    asked about.

    `ignoring` is the (course_code, section) being reassigned. The class being
    handed over should not count against whoever is being offered it.
    """
    wanted = set(weeks)
    busy: dict[str, list[int]] = {sid: [] for sid in staff_ids}

    for c in classes:
        if not c.is_teaching or c.week not in wanted:
            continue
        if c.staff_id not in busy or c.day != day:
            continue
        if ignoring is not None and (c.course_code, c.section) == ignoring:
            continue
        if _minutes(c.start) < _minutes(end) and _minutes(start) < _minutes(c.end):
            busy[c.staff_id].append(c.week)

    return {sid: sorted(set(weeks_busy)) for sid, weeks_busy in busy.items()}


def load_by_staff(classes: list[Class]) -> dict[str, dict[int, int]]:
    """Teaching minutes per staff member per week."""
    load: dict[str, dict[int, int]] = {}
    for c in classes:
        if not c.is_teaching:
            continue
        load.setdefault(c.staff_id, {})
        load[c.staff_id][c.week] = load[c.staff_id].get(c.week, 0) + c.minutes
    return load


def classes_for(classes: list[Class], staff_id: str, week: int | None = None) -> list[Class]:
    """One person's teaching, optionally narrowed to a single week."""
    return [
        c
        for c in classes
        if c.staff_id == staff_id and (week is None or c.week == week) and c.is_teaching
    ]


def validate(
    weeks: list[Week],
    staff: list[StaffMember],
    timetable: list[TimetableRow],
    exceptions: list[ExceptionRow],
) -> list[str]:
    """Problems with the data itself, as opposed to problems with the timetable.

    The spreadsheet version of this tool failed silently when the data was wrong.
    Anything that would produce a misleading answer should be reported here
    instead.
    """
    issues: list[str] = []
    week_numbers = {w.number for w in weeks}
    staff_ids = {s.id for s in staff}

    if len(week_numbers) != len(weeks):
        issues.append("Weeks: duplicate week numbers.")

    seen_staff: set[str] = set()
    for s in staff:
        if s.id in seen_staff:
            issues.append(f"Staff: duplicate id {s.id!r}.")
        seen_staff.add(s.id)

    # Timetable
    coverage: dict[tuple[str, str], dict[int, list[int]]] = {}
    for row in timetable:
        where = f"{row.course_code} {row.section}"
        if row.day not in WEEKDAYS:
            issues.append(f"{where}: {row.day!r} is not a day of the week.")
        if _minutes(row.end) <= _minutes(row.start):
            issues.append(f"{where}: ends at or before it starts.")
        if row.staff_id is not None and row.staff_id not in staff_ids:
            issues.append(f"{where}: staff id {row.staff_id!r} is not in the staff list.")
        if not row.weeks:
            issues.append(f"{where}: no weeks ticked, so it never runs.")
        for w in row.weeks:
            if w not in week_numbers:
                issues.append(f"{where}: week {w} is not in the teaching calendar.")
            coverage.setdefault(row.key, {}).setdefault(w, []).append(row.id)

    # The failure that broke the spreadsheet: one section covered twice in a week.
    for (code, section), by_week in coverage.items():
        doubled = sorted(w for w, ids in by_week.items() if len(ids) > 1)
        if doubled:
            issues.append(
                f"{code} {section}: covered by more than one timetable row in "
                f"week(s) {', '.join(str(w) for w in doubled)}. "
                "This creates duplicate classes and false clashes."
            )

    # Exceptions
    known = {r.key for r in timetable}
    runs: dict[tuple[int, str, str], bool] = {}
    for row in timetable:
        for w in row.weeks:
            runs[(w, row.course_code, row.section)] = True

    seen_keys: set[tuple[int, str, str]] = set()
    for exc in exceptions:
        where = f"Exception for {exc.course_code} {exc.section} in week {exc.week}"
        if exc.week not in week_numbers:
            issues.append(f"{where}: week {exc.week} is not in the teaching calendar.")
        if exc.staff_id is not None and exc.staff_id not in staff_ids:
            issues.append(f"{where}: staff id {exc.staff_id!r} is not in the staff list.")
        if exc.day is not None and exc.day not in WEEKDAYS:
            issues.append(f"{where}: {exc.day!r} is not a day of the week.")
        if exc.start is not None and exc.end is not None:
            if _minutes(exc.end) <= _minutes(exc.start):
                issues.append(f"{where}: ends at or before it starts.")

        if exc.action is Action.ADD:
            missing = [
                name
                for name, value in (
                    ("staff", exc.staff_id),
                    ("day", exc.day),
                    ("start", exc.start),
                    ("end", exc.end),
                )
                if value is None
            ]
            if missing:
                issues.append(
                    f"{where}: an added class has no timetable row to inherit from, "
                    f"so it needs {', '.join(missing)}."
                )
            continue

        if exc.key in seen_keys:
            issues.append(f"{where}: more than one exception for the same week. Only the first applies.")
        seen_keys.add(exc.key)

        if (exc.course_code, exc.section) not in known:
            issues.append(f"{where}: no timetable row for that course and section.")
        elif not runs.get((exc.week, exc.course_code, exc.section)):
            issues.append(f"{where}: that section does not run in week {exc.week}, so this has no effect.")

    return issues
