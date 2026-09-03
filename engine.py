"""Timetable expansion, staffing and clash prevention.

Pure domain logic. This module knows nothing about databases, HTTP, files or
user interfaces, and it must stay that way. Everything here is a plain function
over plain data, so it can be tested without spinning anything up and reused
whichever way the tool is eventually delivered.

The model, in short:

  Week          one teaching week, numbered 1..n, with real dates attached
  StaffMember   someone the manager staffs, with an optional weekly target
  Course        one offering out of the student management system: its code,
                name, year, semester and the people accountable for it
  TimetableRow  a course and section, its day, time, and the weeks it runs.
                Set externally. It does not say who teaches it.
  Assignment    one person covering one timetable row in one week
  ExceptionRow  a departure from the timetable in a single week
  Class         one course and section actually meeting in one week
  Conflict      why a proposed assignment cannot be made

The timetable is somebody else's document. Staffing is the manager's, so it
lives apart from it, one record per row per week. Splitting a semester between
two people is then two sets of weeks rather than a second timetable row, and a
one week substitution is one record rather than an exception.

A class with nobody on it is not an error. The manager staffs their own people
into a timetable that other teams also teach; an empty slot means "not ours" or
"not yet", and coverage() is what tells those apart from the outside.
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
    target_minutes: int | None = None   # contact time per week, if there is a target


@dataclass(frozen=True)
class Course:
    """One offering, as the student management system has it.

    This is a catalogue, not a plan: most of what it holds is accountability
    rather than teaching. A course coordinator is not the person in the room,
    so nothing here is read as staffing. What the rest of the tool takes from
    it is identity, the code and the name a class is known by.

    Identity is the whole offering, not the code alone: one code can run in
    both semesters, and those are different offerings of the same course.
    """

    code: str
    name: str = ""
    academic_year: str = ""
    semester: str = ""
    occurrence: str = ""
    college: str = ""
    programme: str = ""
    coordinator: str = ""
    coordinator_email: str = ""
    offering_coordinator: str = ""
    offering_coordinator_email: str = ""
    grade_reviewer: str = ""
    grade_reviewer_email: str = ""
    department: str = ""

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.code, self.academic_year, self.semester, self.occurrence)

    @property
    def label(self) -> str:
        return f"{self.code} {self.name}".strip()


@dataclass(frozen=True)
class TimetableRow:
    id: int
    course_code: str
    section: str
    day: str
    start: time
    end: time
    weeks: frozenset[int]

    @property
    def key(self) -> tuple[str, str]:
        return (self.course_code, self.section)

    @property
    def label(self) -> str:
        return f"{self.course_code} {self.section}"


@dataclass(frozen=True)
class Assignment:
    """One person covering one timetable row in one week.

    Per week rather than per range. A range is a display detail, and storing
    ranges would mean splitting and merging them on every edit; storing weeks
    means an assignment is always just written or removed.
    """

    timetable_id: int
    week: int
    staff_id: str


@dataclass(frozen=True)
class ExceptionRow:
    """A single week that departs from the timetable.

    Exceptions are about the timetable, never about staffing: who teaches is an
    assignment, including for one week only. An added class is the exception:
    it has no timetable row for an assignment to attach to, so it carries its
    own staff member.
    """

    id: int
    week: int
    course_code: str
    section: str
    action: Action
    day: str | None = None
    start: time | None = None
    end: time | None = None
    staff_id: str | None = None    # added classes only
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
    def runs(self) -> bool:
        """Does this class meet at all? Cancelled weeks do not."""
        return self.status is not Status.CANCELLED

    @property
    def covered(self) -> bool:
        return self.runs and self.staff_id is not None

    @property
    def is_teaching(self) -> bool:
        """Does this class occupy someone's time?"""
        return (
            self.runs
            and self.staff_id is not None
            and self.start is not None
            and self.end is not None
        )

    @property
    def minutes(self) -> int:
        if self.start is None or self.end is None or not self.runs:
            return 0
        return _minutes(self.end) - _minutes(self.start)


@dataclass(frozen=True)
class Conflict:
    """Why a proposed assignment cannot be made."""

    week: int
    proposed: Class     # the class being handed to someone
    existing: Class     # what they are already doing at that time


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


@dataclass(frozen=True)
class Departure:
    """A set of weeks that does not look like the person's usual week.

    It carries both the whole week and the difference, because a reader wants
    the difference ("also teaching X") and a renderer sometimes wants the week.
    """

    weeks: tuple[int, ...]
    classes: tuple[Class, ...]
    added: tuple[Class, ...]                       # not in the usual week
    gone: tuple[Class, ...]                        # in the usual week, not here
    moved: tuple[tuple[Class, Class], ...]         # (usually, this week)
    cancelled: tuple[Class, ...]


@dataclass(frozen=True)
class Shape:
    """One person's semester as the week they repeat, and the weeks that depart.

    A twelve week semester is rarely twelve different weeks. It is usually one
    week repeated, with a handful of exceptions, and saying it that way is the
    difference between a page somebody reads and a page they scroll past.
    """

    staff_id: str
    usual: tuple[Class, ...]
    usual_weeks: tuple[int, ...]
    departures: tuple[Departure, ...]

    @property
    def is_settled(self) -> bool:
        """Every week the same. Nothing to say beyond the grid."""
        return not self.departures

    @property
    def minutes(self) -> int:
        return sum(c.minutes for c in self.usual)


@dataclass(frozen=True)
class Coverage:
    """How much of the timetable has somebody on it."""

    total: int                      # class weeks that run and so need somebody
    covered: int
    uncovered: tuple[Class, ...]

    @property
    def percent(self) -> int:
        return 100 if self.total == 0 else round(100 * self.covered / self.total)


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _collides(a_start: time, a_end: time, b_start: time, b_end: time) -> bool:
    """Touching is not overlapping: 12:00 to 13:00 clears 11:00 to 12:00."""
    return _minutes(a_start) < _minutes(b_end) and _minutes(b_start) < _minutes(a_end)


def overlaps(a: Class, b: Class) -> bool:
    """True when two classes collide for the person teaching them both."""
    if not (a.is_teaching and b.is_teaching):
        return False
    if a.week != b.week or a.day != b.day or a.staff_id != b.staff_id:
        return False
    return _collides(a.start, a.end, b.start, b.end)


def course_names(courses: list[Course]) -> dict[str, str]:
    """Code to name. A course keeps its name across offerings, so the code is enough."""
    names: dict[str, str] = {}
    for course in courses:
        if course.name and not names.get(course.code):
            names[course.code] = course.name
    return names


def expand(
    timetable: list[TimetableRow],
    exceptions: list[ExceptionRow],
    assignments: list[Assignment],
    courses: list[Course] | None = None,
) -> list[Class]:
    """Build every class in every week, with its staffing and exceptions applied.

    Names come from the course catalogue rather than the timetable, so there is
    one place a course is named. A class whose code is not in the catalogue
    still expands; it simply has no name, and validate() says so.

    A cancelled class keeps whoever was assigned to it, so the interface can say
    "Alice, cancelled" rather than dropping the week out of her semester with no
    explanation. It does not count as teaching, so it neither blocks an
    assignment nor adds to a load.
    """
    overrides: dict[tuple[int, str, str], ExceptionRow] = {}
    for exc in exceptions:
        if exc.action is Action.ADD:
            continue
        overrides.setdefault(exc.key, exc)

    staffing = {(a.timetable_id, a.week): a.staff_id for a in assignments}
    names = course_names(courses or [])

    classes: list[Class] = []

    for row in timetable:
        for week in sorted(row.weeks):
            base = Class(
                week=week,
                course_code=row.course_code,
                course_title=names.get(row.course_code, ""),
                section=row.section,
                staff_id=staffing.get((row.id, week)),
                day=row.day,
                start=row.start,
                end=row.end,
                status=Status.SCHEDULED,
                timetable_row_id=row.id,
            )

            exc = overrides.get((week, row.course_code, row.section))
            if exc is None:
                classes.append(base)
                continue

            if exc.action is Action.CANCEL:
                classes.append(
                    replace(base, status=Status.CANCELLED, exception_id=exc.id)
                )
                continue

            # CHANGE: only the fields the exception supplies are overridden, and
            # staffing is never one of them.
            classes.append(
                replace(
                    base,
                    status=Status.CHANGED,
                    exception_id=exc.id,
                    day=exc.day if exc.day is not None else row.day,
                    start=exc.start if exc.start is not None else row.start,
                    end=exc.end if exc.end is not None else row.end,
                )
            )

    for exc in exceptions:
        if exc.action is not Action.ADD:
            continue
        classes.append(
            Class(
                week=exc.week,
                course_code=exc.course_code,
                course_title=names.get(exc.course_code, ""),
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


# ------------------------------------------------------------ assignment

def check_assignment(
    classes: list[Class],
    staff_id: str,
    timetable_id: int | None = None,
    weeks: list[int] | None = None,
    exception_id: int | None = None,
) -> list[Conflict]:
    """What stops this person taking this class in these weeks.

    An empty list means the assignment is safe to write. This is the check that
    makes a clash unreachable rather than merely visible: the interface greys
    out the people it would return conflicts for, and the API refuses the write
    if one is attempted anyway.

    The class being assigned never counts against the person being offered it,
    so handing a row to whoever already holds part of it is not a conflict with
    themselves.
    """
    if timetable_id is not None:
        targets = [c for c in classes if c.timetable_row_id == timetable_id]
    elif exception_id is not None:
        targets = [
            c for c in classes
            if c.exception_id == exception_id and c.status is Status.ADDED
        ]
    else:
        return []

    if weeks is not None:
        wanted = set(weeks)
        targets = [c for c in targets if c.week in wanted]

    conflicts: list[Conflict] = []
    for target in targets:
        if not target.runs or target.start is None or target.end is None:
            continue
        for other in classes:
            if other.staff_id != staff_id or not other.is_teaching:
                continue
            if other.week != target.week or other.day != target.day:
                continue
            if _same_slot(other, target):
                continue
            if _collides(other.start, other.end, target.start, target.end):
                conflicts.append(
                    Conflict(week=target.week, proposed=target, existing=other)
                )

    conflicts.sort(key=lambda c: (c.week, c.existing.label))
    return conflicts


def _same_slot(a: Class, b: Class) -> bool:
    """Are these the same class, so not something to be in conflict with?"""
    if a.timetable_row_id is not None and b.timetable_row_id is not None:
        return a.timetable_row_id == b.timetable_row_id and a.week == b.week
    if a.exception_id is not None and b.exception_id is not None:
        return a.exception_id == b.exception_id and a.week == b.week
    return False


def who_is_free(
    classes: list[Class],
    staff_ids: list[str],
    day: str,
    start: time,
    end: time,
    weeks: list[int],
    ignoring: int | None = None,
) -> dict[str, list[int]]:
    """Which weeks each person is already busy in, for a proposed slot.

    Answers the question the manager actually has when staffing something: if
    not them, then who? An empty list means that person is free for every week
    asked about.

    `ignoring` is the timetable row being assigned. Whoever already covers part
    of it should not be marked busy on account of the very class being offered.
    """
    wanted = set(weeks)
    busy: dict[str, list[int]] = {sid: [] for sid in staff_ids}

    for c in classes:
        if not c.is_teaching or c.week not in wanted:
            continue
        if c.staff_id not in busy or c.day != day:
            continue
        if ignoring is not None and c.timetable_row_id == ignoring:
            continue
        if _collides(c.start, c.end, start, end):
            busy[c.staff_id].append(c.week)

    return {sid: sorted(set(weeks_busy)) for sid, weeks_busy in busy.items()}


def group_assignments(
    assignments: list[Assignment],
) -> dict[int, list[tuple[str, tuple[int, ...]]]]:
    """Per timetable row, who covers it and in which weeks.

    Storage is per week; people read ranges. This is where the two meet.
    """
    grouped: dict[int, dict[str, set[int]]] = {}
    for a in assignments:
        grouped.setdefault(a.timetable_id, {}).setdefault(a.staff_id, set()).add(a.week)

    return {
        row_id: sorted(
            ((sid, tuple(sorted(weeks))) for sid, weeks in by_staff.items()),
            key=lambda pair: pair[1][0],
        )
        for row_id, by_staff in grouped.items()
    }


# ------------------------------------------------------------ reporting

def coverage(classes: list[Class]) -> Coverage:
    """How much of the timetable has somebody on it, and what does not."""
    running = [c for c in classes if c.runs]
    uncovered = [c for c in running if c.staff_id is None]
    return Coverage(
        total=len(running),
        covered=len(running) - len(uncovered),
        uncovered=tuple(uncovered),
    )


def uncovered_rows(classes: list[Class]) -> list[dict]:
    """Uncovered class weeks gathered per course and section.

    Thirty six uncovered weeks are rarely thirty six decisions. Grouping them
    turns the list into the handful of things that actually need staffing.
    """
    grouped: dict[tuple[str, str], dict] = {}
    for c in classes:
        if c.runs and c.staff_id is None:
            entry = grouped.setdefault(
                (c.course_code, c.section),
                {
                    "course_code": c.course_code,
                    "course_title": c.course_title,
                    "section": c.section,
                    "day": c.day,
                    "timetable_row_id": c.timetable_row_id,
                    "exception_id": c.exception_id,
                    "weeks": [],
                },
            )
            entry["weeks"].append(c.week)

    rows = list(grouped.values())
    for r in rows:
        r["weeks"] = sorted(r["weeks"])
    rows.sort(key=lambda r: (-len(r["weeks"]), r["course_code"], r["section"]))
    return rows


def _in_order(group: list[Class]) -> list[Class]:
    return sorted(group, key=lambda c: (
        WEEKDAYS.index(c.day) if c.day in WEEKDAYS else len(WEEKDAYS),
        _minutes(c.start) if c.start else 0,
        c.label,
    ))


def _source(c: Class) -> tuple[str, int | None]:
    """What a class IS, for telling one week's classes against another's.

    Not the label: an added session carries the same course and section as the
    class it sits beside, so matching on the label would fold an extra crit into
    the studio it is extra to.
    """
    if c.timetable_row_id is not None:
        return ("row", c.timetable_row_id)
    return ("added", c.exception_id)


def _signature(group: list[Class]) -> tuple:
    """What makes two weeks the same week, for this purpose."""
    return tuple(sorted(
        (
            c.label,
            c.day or "",
            "" if c.start is None else c.start.isoformat(),
            "" if c.end is None else c.end.isoformat(),
            c.status.value,
        )
        for c in group
    ))


def usual_week(classes: list[Class], staff_id: str, weeks: list[int]) -> Shape:
    """The week this person repeats, and every week that departs from it.

    The usual week is the one they have most often; ties go to whichever starts
    earlier, so the answer does not wander between runs. A week where they teach
    nothing is a week like any other and can itself be the usual one.
    """
    by_week: dict[int, list[Class]] = {w: [] for w in weeks}
    for c in classes:
        if c.staff_id == staff_id and c.week in by_week:
            by_week[c.week].append(c)

    if not by_week:
        return Shape(staff_id=staff_id, usual=(), usual_weeks=(), departures=())

    patterns: dict[tuple, list[int]] = {}
    for week in sorted(by_week):
        patterns.setdefault(_signature(by_week[week]), []).append(week)

    ranked = sorted(patterns.items(), key=lambda item: (-len(item[1]), item[1][0]))
    _, usual_weeks = ranked[0]
    usual = tuple(_in_order(by_week[usual_weeks[0]]))
    usually = {_source(c): c for c in usual}

    departures = []
    for _, weeks_here in ranked[1:]:
        group = _in_order(by_week[weeks_here[0]])
        here = {_source(c): c for c in group}
        departures.append(Departure(
            weeks=tuple(weeks_here),
            classes=tuple(group),
            added=tuple(c for c in group if c.runs and _source(c) not in usually),
            gone=tuple(c for c in usual if _source(c) not in here),
            moved=tuple(
                (usually[_source(c)], c)
                for c in group
                if c.runs and _source(c) in usually
                and (c.day, c.start, c.end) != (usually[_source(c)].day,
                                                usually[_source(c)].start,
                                                usually[_source(c)].end)
            ),
            cancelled=tuple(c for c in group if not c.runs),
        ))

    departures.sort(key=lambda d: d.weeks[0])
    return Shape(
        staff_id=staff_id,
        usual=usual,
        usual_weeks=tuple(usual_weeks),
        departures=tuple(departures),
    )


def shapes(classes: list[Class], staff: list[StaffMember], weeks: list[int]) -> list[Shape]:
    """Everybody's semester, each as a usual week and its departures."""
    return [usual_week(classes, person.id, weeks) for person in staff]


def teachers_for(classes: list[Class]) -> dict[str, list[str]]:
    """Who actually teaches each course, per course code.

    Derived from staffing and nothing else. The catalogue names a course
    coordinator and an offering coordinator, and neither of them is this: a
    coordinator is accountable for a course, not in the room. Keeping the two
    apart is the whole reason this is a function over classes rather than a
    column on Course.
    """
    found: dict[str, list[str]] = {}
    for c in classes:
        if not c.is_teaching:
            continue
        who = found.setdefault(c.course_code, [])
        if c.staff_id not in who:
            who.append(c.staff_id)
    return {code: sorted(who) for code, who in found.items()}


def find_clashes(classes: list[Class]) -> list[Clash]:
    """Every pair of classes the same person cannot both attend.

    Assignments are checked before they are written, so this should stay empty.
    It is kept because an import or a hand edit to the timetable can move a
    class on top of one already staffed, and silence would be the wrong answer.
    """
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
    """Clashes grouped into distinct problems, with the weeks each occurs in."""
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


def load_by_staff(classes: list[Class]) -> dict[str, dict[int, int]]:
    """Teaching minutes per staff member per week."""
    load: dict[str, dict[int, int]] = {}
    for c in classes:
        if not c.is_teaching:
            continue
        load.setdefault(c.staff_id, {})
        load[c.staff_id][c.week] = load[c.staff_id].get(c.week, 0) + c.minutes
    return load


def over_target(
    staff: list[StaffMember], classes: list[Class]
) -> list[tuple[str, int, int, int]]:
    """Weeks where somebody is timetabled past their target.

    Returns (staff_id, week, minutes, target). Only people with a target set
    can be over it.
    """
    load = load_by_staff(classes)
    out = []
    for person in staff:
        if not person.target_minutes:
            continue
        for week, minutes in sorted(load.get(person.id, {}).items()):
            if minutes > person.target_minutes:
                out.append((person.id, week, minutes, person.target_minutes))
    return out


def classes_for(classes: list[Class], staff_id: str, week: int | None = None) -> list[Class]:
    """One person's semester, optionally narrowed to a single week.

    Cancelled classes are included: a week that empties out because a class was
    cancelled should say so rather than just look free.
    """
    return [
        c
        for c in classes
        if c.staff_id == staff_id and (week is None or c.week == week)
    ]


# ------------------------------------------------------------ validation

def validate(
    weeks: list[Week],
    staff: list[StaffMember],
    timetable: list[TimetableRow],
    exceptions: list[ExceptionRow],
    assignments: list[Assignment],
    courses: list[Course] | None = None,
    planning: tuple[str, str] | None = None,
) -> list[str]:
    """Problems with the data itself, as opposed to gaps in the staffing.

    The spreadsheet version of this tool failed silently when the data was
    wrong. Anything that would produce a misleading answer is reported here
    instead. An unstaffed class is not one of those: that is a normal state,
    and coverage() reports it.
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
    coverage_map: dict[tuple[str, str], dict[int, list[int]]] = {}
    for row in timetable:
        where = row.label
        if row.day not in WEEKDAYS:
            issues.append(f"{where}: {row.day!r} is not a day of the week.")
        if _minutes(row.end) <= _minutes(row.start):
            issues.append(f"{where}: ends at or before it starts.")
        if not row.weeks:
            issues.append(f"{where}: no weeks ticked, so it never runs.")
        for w in row.weeks:
            if w not in week_numbers:
                issues.append(f"{where}: week {w} is not in the teaching calendar.")
            coverage_map.setdefault(row.key, {}).setdefault(w, []).append(row.id)

    # The failure that broke the spreadsheet: one section covered twice in a week.
    for (code, section), by_week in coverage_map.items():
        doubled = sorted(w for w, ids in by_week.items() if len(ids) > 1)
        if doubled:
            issues.append(
                f"{code} {section}: covered by more than one timetable row in "
                f"week(s) {', '.join(str(w) for w in doubled)}. "
                "This creates duplicate classes and false clashes."
            )

    # Courses
    catalogue = courses or []
    seen_offerings: set[tuple[str, str, str, str]] = set()
    for course in catalogue:
        if course.key in seen_offerings:
            issues.append(
                f"Courses: {course.code} appears twice for the same year, "
                "semester and occurrence."
            )
        seen_offerings.add(course.key)

    # A timetable naming a course nobody has heard of is worth saying out loud:
    # the class will have no name anywhere in the tool.
    if catalogue:
        known = {c.code for c in catalogue}
        for code in sorted({r.course_code for r in timetable} - known):
            issues.append(
                f"{code}: not in the course list, so it has no name. "
                "Import the course, or correct the code."
            )

        if planning:
            year, semester = planning
            running = {
                c.code for c in catalogue
                if c.academic_year == year and c.semester == semester
            }
            for code in sorted({r.course_code for r in timetable} & known - running):
                issues.append(
                    f"{code}: in the course list, but not as an offering in "
                    f"{semester} {year}, which is what you are planning."
                )

    # Assignments
    rows_by_id = {r.id: r for r in timetable}
    for a in sorted(assignments, key=lambda a: (a.timetable_id, a.week)):
        where = f"Assignment in week {a.week}"
        row = rows_by_id.get(a.timetable_id)
        if row is None:
            issues.append(f"{where}: no timetable row {a.timetable_id}.")
            continue
        if a.staff_id not in staff_ids:
            issues.append(
                f"{row.label} week {a.week}: staff id {a.staff_id!r} is not in "
                "the staff list."
            )
        if a.week not in row.weeks:
            issues.append(
                f"{row.label}: staffed in week {a.week}, which it does not run in."
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
        if exc.day is not None and exc.day not in WEEKDAYS:
            issues.append(f"{where}: {exc.day!r} is not a day of the week.")
        if exc.start is not None and exc.end is not None:
            if _minutes(exc.end) <= _minutes(exc.start):
                issues.append(f"{where}: ends at or before it starts.")

        if exc.action is Action.ADD:
            if exc.staff_id is not None and exc.staff_id not in staff_ids:
                issues.append(f"{where}: staff id {exc.staff_id!r} is not in the staff list.")
            missing = [
                name
                for name, value in (
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

        if exc.staff_id is not None:
            issues.append(
                f"{where}: staffing does not belong in an exception. Assign the "
                "week to somebody instead."
            )

        if exc.key in seen_keys:
            issues.append(f"{where}: more than one exception for the same week. Only the first applies.")
        seen_keys.add(exc.key)

        if (exc.course_code, exc.section) not in known:
            issues.append(f"{where}: no timetable row for that course and section.")
        elif not runs.get((exc.week, exc.course_code, exc.section)):
            issues.append(f"{where}: that section does not run in week {exc.week}, so this has no effect.")

    return issues
