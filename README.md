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

### Over HTTPS

Point it at a certificate and it serves TLS instead. A local one from
[mkcert](https://github.com/FiloSottile/mkcert) works:

```
mkcert localhost 127.0.0.1
python app.py --cert localhost+1.pem --key localhost+1-key.pem
```

`TIMETABLE_CERT` and `TIMETABLE_KEY` do the same thing if you would rather not
type them, and `--host`, `--port` and `--db` are there too. Give both `--cert`
and `--key` or neither; either alone stops with a message rather than starting
half configured.

If the log fills with `Invalid HTTP request received` and nothing loads, a
browser is speaking plain HTTP to the HTTPS port. Use the `https://` address the
banner prints. `ConnectionResetError` alongside it is the same thing seen from
the other end, and is harmless.

### Which database

`timetable.db` beside `app.py`, unless `--db` or `TIMETABLE_DB` says otherwise.
The banner prints the file it is reading, so there is never a question of which
one is in play.

The schema is prepared when the database is first opened, not only at startup,
so however the app is launched -- a wrapper, a different server, an editor's run
button -- it cannot end up serving requests against a database it never set up.

The database is a single file, `timetable.db`, created next to `app.py` on
first run and loaded with sample data. Setup can take that sample out again, or
clear the lot. Deleting the file starts over.

## How the data fits together

Five things you hold, one thing the tool works out.

**Weeks** is the teaching calendar, and it belongs to a semester. Weeks are
numbered consecutively through teaching, so a break is a gap between dates
rather than an extra week.

You do not enter them one at a time. Setup asks when teaching starts, how many
weeks it runs, and when the breaks are, and builds the calendar from that,
noting the break on the week before it. A start that is not a Monday is taken as
the Monday of that week.

**A term** is a year and a semester together, and the plan belongs to one. The
calendar, the timetable, the exceptions and the staffing are all a term's; the
course catalogue is not, because a course keeps its name whichever semester you
are planning. The picker at the top of every page switches between terms, and
naming a semester with nothing in it is how you start planning a new one. Week 1
of S1FS 2028 and week 1 of S2FS 2027 are different weeks with different dates,
and neither disturbs the other.

**Staff** is the people you are responsible for. Each can have a target of
contact hours a week, which is what the Load page and the utilisation bars
measure against. It is optional.

**Courses** is the catalogue, imported from the student management system. It
is reference, not plan: most of what it holds is accountability rather than
teaching, and nothing in it is read as staffing. **A course coordinator is not
the person in the room, and the tool never treats one as staff.** Coordinators
are text on the course record; staff are their own records with their own ids,
and an assignment can only ever name a staff member. Nothing derives one from
the other, in either direction. The Courses page shows both side by side so the
difference is visible: who is accountable, and who is actually teaching. What the rest of the tool takes from it is identity,
the code and the name a class is known by. It will normally hold more courses
than you timetable, which is fine.

Identity is the whole offering, not the code alone: one code running in both
semesters is two records.

**Timetable** is one row per course and section: day, time, and the weeks it
runs. It names neither the course nor the teacher. The name comes from the
catalogue, the teacher is an assignment. Import it from the published
spreadsheet and correct it by hand when the timetable is reissued.

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

*Needs somebody* is grouped by course and section rather than listed a week at a
time, emptiest first, and searchable by course, section or day. It shows the
first twenty five and says how many more there are, because a school that has
just imported a timetable and staffed none of it has hundreds, and a list that
long is not a list anybody reads.

**Planner** is where staffing is decided. One row per class, showing who covers
which weeks as named spans over a ribbon of the semester, so a gap is visible
without reading anything. Each person keeps the same colour throughout.

Search narrows the list by course, section or day, and *Needs somebody* narrows
it to the gaps. Tick rows to act on several at once: assign them all to one
person, take everybody off them, or delete them. The header tick takes only what
the filter is currently showing, and a selection survives changing the filter.

Bulk assignment is checked the same way single assignment is, one class at a
time, so it cannot make a double booking. It reports how many took and names the
classes the person was already busy for.

*Assign* opens underneath the row. Choose the weeks first, then the person.
Everyone who could take it comes first with their current hours against their
target; everyone who could not is greyed out and says which weeks they are
busy. Because busy people are marked before you choose, a clash cannot be made
by accident. Taking weeks somebody else holds asks first.

The refusal is enforced in the API as well as shown in the interface, so it
holds however the write arrives.

**Staff** answers three questions, and a switch at the top picks which. Whichever
you looked at last is what you get next time.

*Each person* is their semester as the week they repeat, then only the weeks
that depart from it. A twelve week semester is rarely twelve different weeks,
and the version of this page that showed all of them ran to four thousand pixels
of near identical cards with the few weeks that mattered lost among them.

So each person gets one grid of their usual week, and underneath it a line per
departure: a class cancelled, a class moved, an extra session, or a class that
is somebody else's for those weeks. Every grid is drawn to the same scale, so
two people can be compared. Colour down the left edge is the day, never the
person, matching the day key at the foot of the page. No day is red, because
red means a clash and nothing else.

Which week counts as usual is the one held most often; a tie goes to whichever
comes first, so the answer does not wander between visits.

*The whole team* is everyone at once in one week, laid out as the week is. Free
time is the empty space, which is what you are looking at when you have a class
to give away. Pick the week along the top.

Classes nobody is on are not drawn here, and the count of them links to the
Dashboard instead. This view answers "who is free", and a term nobody has
staffed yet fills it with dashed blocks and a tile per gap until the empty space
you came for is buried under the very thing you were going to use it for.

*The semester* is every commitment as a bar across the twelve weeks. A handover
is one bar stopping where another starts, so a split semester, a cancelled week
and a three week lecture are all the same picture, read left to right.

Colour means the day in the first mode, because within one person the day is
what there is to tell apart; it means the person in the other two, because there
the people are.

*Export* is a workbook: a summary sheet of hours per person per week, then a
sheet each laying their usual week out as a calendar, with the weeks that depart
from it underneath. *Print* puts the view you are looking at on paper, one
person to a page. Both are built from the same shapes the page draws, so a
printout and the screen cannot disagree.

**Load** is contact hours per person per week, against their target. Timetabled
minutes only, so it will not match a workload allocation that also covers
supervision, marking and admin.

**Exceptions** lists every week that departs from the timetable.

**Setup** holds staff, the teaching calendar, the timetable import, the year
and semester you are planning, and the sample data controls.

Staff is a table you type into. Change a cell and it saves when you leave it;
type a name into the blank row at the bottom and that person exists, with a
fresh blank row underneath. Adding a team is a run of typing rather than six
trips through a dialog. Saving puts the caret back in the cell it came from, so
nothing moves under you.

Names are written the way people write them: *Kate Ahern*, not *Ahern, Kate*.
The list sorts by that name as typed. An id is derived from the name rather than
asked for, since it is bookkeeping for the records to point at and not something
anybody should have to invent; it is shown so it can be recognised, and changing
one is a delete and re-add, because renaming an id carries somebody's whole
staffing with it and is not a thing to trigger from a half typed cell. If any
names are still written surname first, the panel offers to turn them round.

*Remove the sample data* takes out only what the app invented and leaves
anything you have imported or typed, which matters because the sample uses real
course codes: a blunt delete could take a real record with it. *Clear
everything* is the other one, and means it. Either way it stays gone; a
database somebody has emptied is not refilled on the next run.

Naming the year and semester is optional. It is used for one thing: saying when
a timetabled class is not an offering in the semester you are planning, which
usually means a wrong course code.

## Importing

Both imports show a preview before anything is written, and both refuse a file
they cannot read rather than importing half of it.

### A course catalogue

Courses takes the export from the student management system, as CSV or Excel.
It needs a header row with at least a course code and a course name; every
other column is taken if it is there:

```
Course Code, Academic Year, Semester, Occurrence, Course Name, College,
Primary Programme, Course Coordinator, Course Coordinator Email,
Offering Coordinator, Offering Coordinator Email, Grade Reviewer,
Grade Reviewer Email, Offering Department
```

Codes arrive from a spreadsheet as numbers and are kept as codes: `133150`, not
`133150.0`. The four coordinator columns are matched exactly, because
`Course Coordinator` and `Course Coordinator Email` are two different things
and folding them together would be worse than failing.

Three ways to write it, because an export is usually one semester of a larger
catalogue:

- *Add these to the catalogue* updates what it matches and adds the rest, and
  touches nothing else. Importing the same export twice changes nothing.
- *Replace S2FS 2027* refreshes only the semesters the file covers, so a course
  that has been dropped from that semester goes, and the other semester is left
  alone. The button names the semesters it found.
- *Replace the whole catalogue* deletes everything first, including semesters
  the file says nothing about. It asks before it does.

An imported row is yours, whatever it replaced. Importing over a course the
sample supplied hands it over: it stops being sample data and stays when the
sample is removed.

### A timetable

The Planner does this, beside the classes it is about. Three things sit in its
header:

- **Blank template** downloads a spreadsheet with the right columns and an
  Example sheet showing the week syntax. The header row is generated from the
  same list the parser reads, so a template with columns the tool will not
  accept is not possible.
- **Export** downloads this term's timetable, named for the term, ready to edit
  in Excel and import again.
- **Import…** reads one back.

The file needs a header row with columns for course code, section, day, start,
end and weeks. Headers are matched loosely, so `Course Code`, `course code` and
`Code` are all understood, as are `Activity` or `Class` for the section.

An export carries two more columns, **Course Name** and **Assigned**, greyed in
the header because they are there to be read. The parser ignores both. A course
is named by the catalogue so it is named in one place, and staffing is decided
on the Planner where every assignment is checked against everything else that
person teaches. A spreadsheet is not a second way in past that check.

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

## Deleting

Delete is one click on the bin, with no dialog, and the toast offers to put it
back for a few seconds. Two clicks were never safety; they were friction. The
undo is what makes it safe, and it is what makes deleting a whole selection at
once reasonable to offer.

Putting something back restores what went with it. Deleting a class takes its
staffing, and deleting a person takes theirs, so both are captured before the
delete and replayed after. If a slot was taken in the meantime the rest still
comes back and the part that could not is named rather than dropped quietly.

## Data problems

Above the Planner, Exceptions and Setup pages, an amber panel lists problems
with the records rather than with the staffing: two rows covering the same
section in one week, staff ids that do not exist, assignments to weeks a class
does not run in, staffing written into an exception, incomplete added classes,
backwards times, a timetabled course that is not in the catalogue, and a course
that is in the catalogue but not as an offering in the semester you are
planning.

The first of those is worth knowing about. Two rows covering the same section in
the same week produces duplicate classes and a clash that is not real. It is the
failure that made the spreadsheet version untrustworthy, so it is reported by
name rather than silently absorbed.

### The timetable and the catalogue

The last two of those get their own panel at the foot of the Courses page, where
they can be acted on rather than only read. It lists the codes timetabled here
that the catalogue does not have for this semester, and hands them to the
Planner with their rows ticked, where deleting is one click and comes back with
an undo.

It hands them over rather than deleting them itself on purpose. Course codes are
matched exactly, so a stray space reads as a course nobody has heard of and
looks identical to the real one on the page. Where that happens the code is
shown in quotes and said to have a space in it, and the fix is usually to
correct the code rather than to delete the class. A delete button wired straight
to a typo detector is the wrong shape.

Underneath, the courses the catalogue offers this semester with nothing on the
timetable. That one is a list and nothing more. Usually it is right — somebody
else teaches them — and the catalogue is the whole institution while this tool
staffs a corner of it, so nothing here ever removes a course from it.

## Layout

```
engine.py     the rules: expansion, staffing, conflicts, coverage, load,
              the usual week, the calendar, validation
importer.py   reading a timetable and a course catalogue out of spreadsheets
sheets.py     writing the template, the export and the staff calendars
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

`usual_week` is the other rule worth naming. It reduces a person's semester to
the week they repeat plus a list of departures, and it belongs here rather than
in the browser because deciding what makes two weeks the same week is a rule
about timetables, not a rendering detail. It matches classes by where they come
from rather than by their label, so an extra session of a course is a departure
from the class it sits beside rather than the same thing counted twice.

## Tests

```
python -m pytest
```

217 tests. The engine cases came from two real course outlines: a lecture
running in three weeks only, workshops shortened in those weeks so the lecturer
is not double booked, a public holiday cancellation, a one week substitution,
split semester teaching, and an added crit session.

Refusal has its own tests, since it is the point of the tool: a busy person is
refused, a free one is not, only the weeks that actually overlap are refused,
extending somebody's own class is not a clash with itself, a cancelled week
does not block, a class moved out of the way stops blocking, an added class
both blocks and is blocked, and unassigning frees the slot.

The usual week has its own tests, including the two cases that break a naive
version: a six/six split, where the tie has to resolve the same way every time,
and an added session sharing a course and section with the class beside it,
which must not fold into it.

The catalogue is tested for what a real export does: numeric codes, a course
name with a comma in it, one code in two semesters, and the four coordinator
columns staying apart.

The spreadsheets are tested in both directions at once: every column the tool
writes is one its parser accepts, the blank template reads as an empty
timetable, and a timetable exported and imported again comes back as the same
classes with the same staffing, with the two read-only columns dropped on the
way in. One test asserts the thing the catalogue rests on: no
coordinator is ever a staff member, and who teaches a course comes from
assignments alone.

Sample data has its own tests, including the bug they were written for: the
check for "should this database be seeded" used to ask whether the timetable was
empty, so clearing the sample and restarting brought it straight back, and
importing a catalogue before entering any timetable invited the sample to land
on top of it.

The reconciler is tested against the two mismatches it distinguishes, since they
have different fixes: a code the catalogue has never held, and one it holds for
another semester. An empty catalogue reports nothing, because no catalogue is a
tool nobody has imported courses into, not a timetable where every code is
wrong. One test asserts that the amber panel and the Courses panel agree, which
is the point of computing it once and presenting it twice.

The staff workbook is tested as a document rather than a file: a sheet per
person in the order the page lists them, a class landing in the right day column
and hour row, a two hour class covering four half hour rows without repeating
itself, and the summary carrying the hours a week the Load page shows.

Two more are guards rather than features. One removes the exceptions and
asserts that the clash reappears, so the shortened workshop test cannot pass by
accident if clash detection stops working. The other checks that when a section
appears twice in a week, only the class that actually collides is flagged. A
third asserts no sample name is written surname first, so a convention that was
taken out cannot quietly come back.

## When it will not start

The database is prepared on first use and again at startup, and both paths are
idempotent, so the usual fix is simply to run it again.

A database left half migrated by an interrupted upgrade repairs itself on the
next start, in both directions: a rename that had already happened is finished,
and a calendar stranded in the scratch table is taken back. Nothing holding your
rows is ever dropped.

If the database genuinely cannot be prepared, the app stops with one sentence
naming the file and the problem instead of a traceback on every request.

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
- The catalogue is read, never written back. Nothing here reaches the student
  management system.
- The sample data uses real course codes. Importing your own export over them
  is the intended path and hands those records over to you; removing the sample
  afterwards leaves them alone.
- No notifications yet. The engine returns everything needed to build them.
- Within one term, all courses share one teaching calendar. If some run to a
  different pattern inside a semester, weeks would need a calendar name as well
  as a term.
