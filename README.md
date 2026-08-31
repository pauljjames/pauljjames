# Timetable staffing

Decides who covers a teaching timetable, and stops one person being put in two
places at once. Built for a semester of roughly 36 classes and a dozen or so
staff.

The timetable is set outside this tool and cannot be argued with. What is
decided here is staffing: which of your people covers which class, in which
weeks. An assignment that would double book somebody is refused rather than
reported, so a clash is something you cannot make instead of something you find
later.

Teaching outside this timetable is not tracked, so an empty week here does not
mean that person is free.

## Running it

Python 3.10 or newer.

```
pip install -r requirements.txt
python app.py
```

Then open <http://127.0.0.1:8000>.

The database is a single file, `timetable.db`, created next to `app.py` on
first run and loaded with sample data. Delete that file to start over, or use
Clear everything on the Setup page.

## How the data fits together

Five things you hold, one thing the tool works out.

**Weeks** is the teaching calendar. Weeks are numbered consecutively through
teaching, so a mid semester break is a gap between dates rather than an extra
week. You set the Monday and the end of the week follows.

**Staff** is the people you are responsible for. Each can have a target of
contact hours a week, which is what the Load page and the utilisation bars
measure against. It is optional.

**Timetable** is one row per course and section: day, time, and the weeks it
runs. It does not say who teaches it. Import it from the published spreadsheet
and correct it by hand when the timetable is reissued.

**Assignments** are who covers what, stored one record per class per week. A
class split between two people is two sets of weeks on the same row, not a
second row. A one week substitution is one record. The database holds one
person per class per week as a key rather than a rule in code, so a split
cannot half happen.

**Exceptions** are single weeks that genuinely depart from the timetable. They
never say who teaches: that is an assignment, including for one week only.

- *Change* alters one week's day or time. Fill in only the fields that differ.
- *Cancel* means the class does not run. It stays visible, struck through, so
  an empty week explains itself, and it neither blocks an assignment nor counts
  as load.
- *Add* creates an extra class with no timetable row behind it. Because there
  is no row for an assignment to attach to, it carries its own staff member,
  and is checked for clashes the same way.

**Classes** is what the tool derives: every class in every week, with staffing
and exceptions applied. You never edit it.

A class with nobody on it is not an error. You staff your own people into a
timetable other teams also teach, so an empty slot means "not ours" or "not
yet". Coverage is what tells those apart from the outside.

## The views

**Dashboard** is the front page: how much of the timetable has somebody on it,
what still needs staffing, and what each person is carrying against their
target. The bar is red when somebody's average is over their target; a week by
week spike is flagged beside it instead, because those are different problems.

**Planner** is where staffing is decided. One row per class, showing who covers
which weeks as named spans over a ribbon of the semester, so a gap is visible
without reading anything. Each person keeps the same colour throughout.

*Assign* opens underneath the row. Choose the weeks first, then the person.
Everyone who could take it comes first with their current hours against their
target; everyone who could not is greyed out and says which weeks they are
busy. Because busy people are marked before you choose, a clash cannot be made
by accident. Taking weeks somebody else holds asks first.

The refusal is enforced in the API as well as shown in the interface, so it
holds however the write arrives.

**Staff** is one person's whole semester, week by week. Each class carries a
colour down its left edge for the day it falls on, so a Monday and a Thursday
commitment are distinguishable at a glance. No day is red, because red means a
clash and nothing else. Amber means that week was changed, grey strikethrough
means cancelled.

**Load** is contact hours per person per week, against their target. Timetabled
minutes only, so it will not match a workload allocation that also covers
supervision, marking and admin.

**Exceptions** lists every week that departs from the timetable.

**Setup** holds staff, the teaching calendar, the timetable import, and the
sample data controls.

## Importing a timetable

Setup takes a CSV or Excel file with a header row. It needs columns for course
code, section, day, start, end and weeks; a course title is used if present.
Headers are matched loosely, so `Course Code`, `course code` and `Code` are all
understood, as are `Activity` or `Class` for the section.

Weeks are written the way people write them: `1-12`, `1-6, 8`, `1-3 and 5`,
`Weeks 7-9`. Times take `9:00`, `09:00`, `9.30`, `0900`, `1pm`, and whatever a
spreadsheet hands over for a time cell. Days take `Monday`, `Mon`, `Thurs`.

Nothing is written until you have seen the preview: the rows it read, the rows
it could not, and the staffing that would not survive. Anything it cannot read
is a numbered complaint against a spreadsheet row rather than a silent
omission, and a section appearing twice is refused outright, because two rows
for one section is what makes duplicate classes and false clashes.

On import, staffing is re-attached wherever the same course, section and week
still exist. What no longer has a class under it is listed rather than dropped
quietly.

## Data problems

Above the Planner, Exceptions and Setup pages, an amber panel lists problems
with the records rather than with the staffing: two rows covering the same
section in one week, staff ids that do not exist, assignments to weeks a class
does not run in, staffing written into an exception, incomplete added classes,
backwards times.

The first of those is worth knowing about. Two rows covering the same section in
the same week produces duplicate classes and a clash that is not real. It is the
failure that made the spreadsheet version untrustworthy, so it is reported by
name rather than silently absorbed.

## Layout

```
engine.py     the rules: expansion, staffing, conflicts, coverage, load, validation
importer.py   reading a timetable out of a spreadsheet
store.py      SQLite, and nothing else
app.py        HTTP, and nothing else
seed.py       sample data
static/       the browser front end, no build step
```

`engine.py` imports nothing beyond the standard library and knows nothing about
databases, HTTP or the interface. That is deliberate. When the question of where
this should live comes up, whether that turns out to be Lists, Dataverse, Power
Apps or something else, the front end is replaceable and the rules are not.

`check_assignment` is the centre of it: given everything currently timetabled,
a person and a set of weeks, it returns what stands in the way. The interface
uses it to grey people out, and the API uses it to refuse the write.

## Tests

```
python -m pytest
```

122 tests. The engine cases came from two real course outlines: a lecture
running in three weeks only, workshops shortened in those weeks so the lecturer
is not double booked, a public holiday cancellation, a one week substitution,
split semester teaching, and an added crit session.

Refusal has its own tests, since it is the point of the tool: a busy person is
refused, a free one is not, only the weeks that actually overlap are refused,
extending somebody's own class is not a clash with itself, a cancelled week
does not block, a class moved out of the way stops blocking, an added class
both blocks and is blocked, and unassigning frees the slot.

Two of them are guards rather than features. One removes the exceptions and
asserts that the clash reappears, so the shortened workshop test cannot pass by
accident if clash detection stops working. The other checks that when a section
appears twice in a week, only the class that actually collides is flagged.

## Updating

The browser reads `static/` from disk on every load, but the routes live in the
running Python process. Update the files and the interface changes while the
server does not, which shows up as a 404 on something the page expects. The page
checks its version against the server's and says so if they differ, but the
short version is: restart `python app.py` after replacing any files.

## Known limits

- Single user. It is designed to run on one machine, with no accounts and no
  permissions.
- One person per class per week. Team teaching would mean relaxing the
  assignment key and deciding what a clash means when two people share a slot.
- No notifications yet. The engine returns everything needed to build them.
- All courses share one teaching calendar. If some run to a different pattern,
  weeks gain a calendar name and clash detection matches on calendar plus week.
  That is one extra column in three places rather than a rebuild.
