# Timetable clashes

Shows whether a teaching timetable works for the staff you support, and where
it breaks. Built for a semester of roughly 36 courses and a dozen or so staff.

A clash is one person timetabled to two overlapping classes in the same week.
Teaching outside these courses is not tracked, so an empty week here does not
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

Four things you enter, one thing the tool works out.

**Weeks** is the teaching calendar. Weeks are numbered consecutively through
teaching, so a mid semester break is a gap between dates rather than an extra
week. You set the Monday and the end of the week follows.

**Staff** is the people you are responsible for.

**Timetable** is one row per course and section: its usual lecturer, day, time,
and the weeks it runs. A course level lecture that runs in only three weeks is
a row with three weeks ticked. If a section changes lecturer partway through
the semester, add a second row for the later weeks rather than reaching for
exceptions.

**Exceptions** are single weeks that genuinely depart from the timetable. They
are not for staffing. If someone else is teaching, change the timetable so the
table says so.

- *Change* alters one week. Fill in only the fields that differ; anything left
  blank keeps what the timetable says.
- *Cancel* means the class does not run. It stays visible, struck through, so
  an empty week explains itself.
- *Add* creates an extra class with no timetable row behind it, so it needs
  staff, day and both times.

**Classes** is what the tool derives: every class in every week, with exceptions
applied. Clash detection runs against it. You never edit it.

## The views

**Staff** is the front page. One person's whole semester, week by week. Each
class carries a colour down its left edge for the day it falls on, so a Monday
and a Thursday commitment are distinguishable at a glance. The same colours
appear as swatches on the Timetable and Clashes pages. No day is red, because
red means a clash and nothing else. An amber background means that week was
changed, grey strikethrough means cancelled.

**Timetable** is where clashes live, because it is where you fix them. Above
the table, one row per clash: who is affected, the two classes involved, and the
weeks it happens in.

Each clash carries a number, and both halves of the pair carry that same number
in the table below. So eight red rows resolve into four numbered pairs at a
glance, rather than a wall of red with no way to tell what goes with what. Click
a number and everything else dims, leaving just that pair.

Numbers rather than a colour per clash is deliberate. Colour on that page
already means the day of the week, and red already means a problem. A third
colour scheme would fight both.

**Fix this** opens underneath the clash. It shows both colliding classes and,
for each, everyone who could take it instead. People who are free come first
with their current teaching hours; people who are not are greyed out and say
which weeks they are busy. Because busy people are marked before you choose,
handing a class over cannot create a new clash by accident.

You also choose the scope. *Every week it runs* changes the staff on the
timetable row. *Only weeks 1 to 6, splitting the row* leaves the original row
with the weeks it still covers and adds a second row for the rest.

Either way this changes the timetable, never the exceptions. Staffing belongs in
the timetable, so that is where a handover is recorded. Hiding it behind an
exception would leave the Timetable page showing a lecturer who is not actually
teaching, and make the row impossible to edit sensibly afterwards.

Two existing records are updated rather than added to, because for those weeks
they already are where the truth lives: a class that exists only as an added
exception has no timetable row behind it, and a change exception that already
overrides staff would otherwise mask the handover and leave the clash in place.

**Load** is contact hours per person per week. Timetabled minutes only, so it
will not match a workload allocation that also covers supervision, marking and
admin.

**Exceptions** lists every week that departs from the timetable.

**Setup** holds staff, the teaching calendar, and the sample data controls.

## Data problems

Above the Timetable, Exceptions and Setup pages, an amber panel lists problems
with the records rather than the timetable: two rows covering the same section
in one week, staff IDs that do not exist, exceptions pointing at weeks a section
does not run, incomplete added classes, backwards times.

The first of those is worth knowing about. Two rows covering the same section in
the same week produces duplicate classes and a clash that is not real. It is the
failure that made the spreadsheet version untrustworthy, so it is reported by
name rather than silently absorbed.

## Layout

```
engine.py     the rules: expansion, inheritance, overlap, load, validation
store.py      SQLite, and nothing else
app.py        HTTP, and nothing else
seed.py       sample data
static/       the browser front end, no build step
```

`engine.py` imports nothing beyond the standard library and knows nothing about
databases, HTTP or the interface. That is deliberate. When the question of where
this should live comes up, whether that turns out to be Lists, Dataverse, Power
Apps or something else, the front end is replaceable and the rules are not.

## Tests

```
python -m pytest
```

63 tests. The engine cases came from two real course outlines: a lecture running
in three weeks only, workshops shortened in those weeks so the lecturer is not
double booked, a public holiday cancellation, a one week guest lecturer,
split semester teaching, and an added crit session that causes a genuine clash.

Handovers have their own tests: every week changes the row, part of a semester
splits it, a cancelled week stays cancelled and keeps the exceptions that apply
to it, an existing staff override is updated rather than left to mask the change,
and no handover of any shape ever creates an exception.

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

- Single user. It is designed to run on one machine.
- No notifications yet. The engine returns everything needed to build them.
- All courses share one teaching calendar. If some run to a different pattern,
  weeks gain a calendar name and clash detection matches on calendar plus week.
  That is one extra column in three places rather than a rebuild.
