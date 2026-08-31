"""Tests for storage and the HTTP layer.

The engine has its own suite. These check that data survives a round trip
through SQLite unchanged, and that the API does what the interface expects.
"""

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import engine
import seed
import store


@pytest.fixture
def conn(tmp_path):
    c = store.connect(tmp_path / "test.db")
    store.init(c)
    yield c
    c.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "api.db")
    import app as app_module
    importlib.reload(app_module)
    with TestClient(app_module.app) as c:
        yield c


# ------------------------------------------------------------ storage

def test_seed_survives_a_round_trip(conn):
    seed.load(conn)
    weeks, staff, timetable, exceptions = store.load_all(conn)
    assert len(weeks) == 12
    assert len(staff) == 14
    assert len(timetable) == 10
    assert len(exceptions) == 9


def test_week_ticks_survive_a_round_trip(conn):
    seed.load(conn)
    rows = {(r.course_code, r.section): r for r in store.get_timetable(conn)}
    assert rows[("222.702", "LEC")].weeks == frozenset({7, 8, 9})
    assert rows[("111.701", "A")].weeks == frozenset(range(1, 13))


def test_blank_exception_fields_come_back_as_none(conn):
    seed.load(conn)
    shortened = [
        e for e in store.get_exceptions(conn)
        if e.week == 7 and e.section == "WS-A"
    ][0]
    assert shortened.start is not None      # supplied
    assert shortened.staff_id is None       # inherited, not stored as ""
    assert shortened.day is None
    assert shortened.end is None


def test_stored_data_produces_the_expected_clashes(conn):
    seed.load(conn)
    _, _, timetable, exceptions = store.load_all(conn)
    problems = engine.find_problems(engine.expand(timetable, exceptions))
    assert len(problems) == 2
    assert problems[0].weeks == tuple(range(1, 13))
    assert problems[1].weeks == (12,)


def test_editing_a_timetable_row_replaces_its_weeks(conn):
    seed.load(conn)
    row = [r for r in store.get_timetable(conn) if r.section == "LEC"][0]
    store.save_timetable_row(
        conn,
        {
            "course_code": row.course_code, "course_title": row.course_title,
            "section": row.section, "staff_id": row.staff_id, "day": row.day,
            "start": "09:00", "end": "10:00", "weeks": [1, 2],
        },
        row_id=row.id,
    )
    updated = [r for r in store.get_timetable(conn) if r.id == row.id][0]
    assert updated.weeks == frozenset({1, 2})


def test_deleting_a_timetable_row_removes_its_weeks(conn):
    seed.load(conn)
    row = store.get_timetable(conn)[0]
    store.delete_timetable_row(conn, row.id)
    left = conn.execute(
        "SELECT COUNT(*) FROM timetable_weeks WHERE timetable_id = ?", (row.id,)
    ).fetchone()[0]
    assert left == 0


def test_renaming_a_staff_id_follows_through_to_the_timetable(conn):
    seed.load(conn)
    store.save_staff(conn, {"id": "PJ", "name": "Sample, A", "email": ""},
                     original_id="S01")
    rows = store.get_timetable(conn)
    assert any(r.staff_id == "PJ" for r in rows)
    assert not any(r.staff_id == "S01" for r in rows)


# ------------------------------------------------------------ api

def test_state_includes_everything_the_interface_needs(client):
    body = client.get("/api/state").json()
    for key in ("weeks", "staff", "timetable", "exceptions", "classes",
                "problems", "load", "issues"):
        assert key in body
    assert body["issues"] == []
    assert len(body["problems"]) == 2


def test_classes_are_flagged_as_clashing(client):
    classes = client.get("/api/state").json()["classes"]
    flagged = [c for c in classes if c["clashing"]]
    assert {c["label"] for c in flagged} == {
        "111.701 B", "333.703 A", "111.701 A", "222.702 WS-C"}


def test_cancelled_classes_are_returned_but_carry_no_time(client):
    classes = client.get("/api/state").json()["classes"]
    cancelled = [c for c in classes if c["status"] == "Cancelled"]
    assert len(cancelled) == 3
    assert all(c["minutes"] == 0 and c["staff_id"] is None for c in cancelled)


def test_adding_a_class_changes_the_clashes(client):
    before = len(client.get("/api/state").json()["problems"])
    client.post("/api/timetable", json={
        "course_code": "999.999", "course_title": "Clashing course",
        "section": "A", "staff_id": "S03", "day": "Tuesday",
        "start": "14:00", "end": "17:00", "weeks": [1, 2, 3],
    }).raise_for_status()
    after = client.get("/api/state").json()["problems"]
    assert len(after) == before + 1
    added = [p for p in after if p["staff_id"] == "S03"][0]
    assert added["weeks"] == [1, 2, 3]


def test_deleting_a_class_removes_its_clash(client):
    state = client.get("/api/state").json()
    row = [r for r in state["timetable"]
           if r["course_code"] == "333.703"][0]
    client.delete(f"/api/timetable/{row['id']}").raise_for_status()
    assert len(client.get("/api/state").json()["problems"]) == 1


def test_duplicate_week_coverage_is_reported_not_swallowed(client):
    """The failure that made the spreadsheet untrustworthy."""
    client.post("/api/timetable", json={
        "course_code": "111.701", "course_title": "Course One", "section": "A",
        "staff_id": "S10", "day": "Friday", "start": "09:00", "end": "12:00",
        "weeks": [1, 2],
    }).raise_for_status()
    issues = client.get("/api/state").json()["issues"]
    assert any("more than one timetable row" in i for i in issues)


def test_duplicate_staff_id_is_rejected(client):
    res = client.post("/api/staff", json={"id": "S01", "name": "Someone"})
    assert res.status_code == 409


def test_clearing_everything_leaves_a_usable_empty_state(client):
    client.delete("/api/all-data").raise_for_status()
    body = client.get("/api/state").json()
    assert body["timetable"] == []
    assert body["problems"] == []
    assert body["issues"] == []


def test_sample_data_can_be_reloaded(client):
    client.delete("/api/all-data").raise_for_status()
    client.post("/api/sample-data").raise_for_status()
    assert len(client.get("/api/state").json()["problems"]) == 2


def test_the_front_end_is_served(client):
    assert "Timetable clashes" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200


def test_only_the_colliding_class_is_flagged(client):
    """Week 12 has two classes labelled 111.701 A: the usual Tuesday one and an
    added Thursday crit. Only the Thursday one collides, and flagging both would
    send someone looking at the wrong class."""
    classes = client.get("/api/state").json()["classes"]
    week12 = [c for c in classes if c["week"] == 12 and c["label"] == "111.701 A"]
    assert len(week12) == 2
    by_day = {c["day"]: c["clashing"] for c in week12}
    assert by_day == {"Thursday": True, "Tuesday": False}


# ------------------------------------------------------------ resolving clashes

def test_availability_marks_who_could_take_a_slot(client):
    body = client.post("/api/availability", json={
        "day": "Tuesday", "start": "14:00", "end": "17:00",
        "weeks": list(range(1, 13)),
        "course_code": "111.701", "section": "B",
    }).json()
    by_id = {s["id"]: s for s in body["staff"]}
    # S02 currently holds this class, so it is ignored. They still come back
    # busy, because of the other half of their own clash. Handing it back to
    # them would fix nothing, and the list says so.
    assert by_id["S02"]["free"] is False
    assert by_id["S01"]["free"] is False     # teaching 111.701 A at that time
    assert by_id["S10"]["free"] is True      # teaching nothing at all
    assert by_id["S01"]["busy_weeks"] == list(range(1, 13))


def test_availability_ignores_only_the_class_being_handed_over(client):
    """S01 teaches 111.701 A on Tuesday afternoons and nothing else then, so
    offered that very class they must come back free."""
    body = client.post("/api/availability", json={
        "day": "Tuesday", "start": "14:00", "end": "17:00",
        "weeks": list(range(1, 13)),
        "course_code": "111.701", "section": "A",
    }).json()
    by_id = {s["id"]: s for s in body["staff"]}
    assert by_id["S01"]["free"] is True


def test_availability_reports_current_hours(client):
    body = client.post("/api/availability", json={
        "day": "Friday", "start": "09:00", "end": "12:00", "weeks": [1],
    }).json()
    by_id = {s["id"]: s for s in body["staff"]}
    assert by_id["S02"]["minutes"] == 72 * 60
    assert by_id["S10"]["minutes"] == 0


def test_reassigning_every_week_clears_a_structural_clash(client):
    client.post("/api/reassign", json={
        "course_code": "333.703", "section": "A", "staff_id": "S10",
    }).raise_for_status()
    body = client.get("/api/state").json()
    assert len(body["problems"]) == 1                 # only the week 12 one left
    assert body["exceptions"] == sorted(
        body["exceptions"], key=lambda e: (e["week"], e["course_code"]))
    row = [r for r in body["timetable"] if r["course_code"] == "333.703"][0]
    assert row["staff_id"] == "S10"                   # timetable itself changed


def test_reassigning_some_weeks_splits_the_timetable_row(client):
    """Staffing lives in the timetable, so a partial handover splits the row
    rather than hiding the change behind an exception."""
    before = len(client.get("/api/state").json()["exceptions"])
    res = client.post("/api/reassign", json={
        "course_code": "333.703", "section": "A", "staff_id": "S10",
        "weeks": [1, 2, 3],
    }).json()
    assert res["split"] is True

    body = client.get("/api/state").json()
    assert len(body["exceptions"]) == before        # no exception was invented

    rows = [r for r in body["timetable"] if r["course_code"] == "333.703"]
    assert len(rows) == 2
    by_staff = {r["staff_id"]: r["weeks"] for r in rows}
    assert by_staff["S10"] == [1, 2, 3]
    assert by_staff["S02"] == [4, 5, 6, 7, 8, 9, 10, 11, 12]

    problem = [p for p in body["problems"] if p["staff_id"] == "S02"][0]
    assert problem["weeks"] == [4, 5, 6, 7, 8, 9, 10, 11, 12]


def test_the_split_row_keeps_the_timetable_readable(client):
    """The point of splitting: whoever actually teaches a week is visible on the
    Timetable page, not buried in the exceptions list."""
    client.post("/api/reassign", json={
        "course_code": "333.703", "section": "A", "staff_id": "S10",
        "weeks": [1, 2, 3],
    }).raise_for_status()
    body = client.get("/api/state").json()

    for week, expected in ((2, "S10"), (7, "S02")):
        klass = [c for c in body["classes"]
                 if c["week"] == week and c["label"] == "333.703 A"][0]
        assert klass["staff_id"] == expected
        assert klass["status"] == "Scheduled"     # not "Changed"
        assert klass["timetable_row_id"] is not None


def test_reassigning_every_week_does_not_split(client):
    res = client.post("/api/reassign", json={
        "course_code": "333.703", "section": "A", "staff_id": "S10",
    }).json()
    assert res["split"] is False
    rows = [r for r in client.get("/api/state").json()["timetable"]
            if r["course_code"] == "333.703"]
    assert len(rows) == 1


def test_reassigning_updates_an_existing_staff_override(client):
    """Week 5 of 111.701 C is already overridden to a guest lecturer. Changing
    the timetable row alone would leave that week untouched and the clash in
    place, so the existing exception is updated instead of a new one added."""
    before = len(client.get("/api/state").json()["exceptions"])
    client.post("/api/reassign", json={
        "course_code": "111.701", "section": "C", "staff_id": "S13",
        "weeks": [5],
    }).raise_for_status()
    body = client.get("/api/state").json()
    assert len(body["exceptions"]) == before
    week5 = [c for c in body["classes"]
             if c["week"] == 5 and c["label"] == "111.701 C"][0]
    assert week5["staff_id"] == "S13"


def test_reassigning_an_added_class_edits_its_exception(client):
    """The week 12 crit exists only as an exception, so there is no row to edit."""
    before = len(client.get("/api/state").json()["exceptions"])
    client.post("/api/reassign", json={
        "course_code": "111.701", "section": "A", "staff_id": "S11",
        "weeks": [12],
    }).raise_for_status()
    body = client.get("/api/state").json()
    assert len(body["exceptions"]) == before          # edited, not added to
    crit = [e for e in body["exceptions"] if e["action"] == "Add"][0]
    assert crit["staff_id"] == "S11"
    assert not [p for p in body["problems"] if p["staff_id"] == "S01"]


def test_a_cancelled_week_stays_cancelled_after_a_handover(client):
    """Week 8 does not run. Splitting the row must not quietly revive it."""
    client.post("/api/reassign", json={
        "course_code": "222.702", "section": "WS-A", "staff_id": "S12",
        "weeks": [7, 8, 9],
    }).raise_for_status()
    body = client.get("/api/state").json()
    week8 = [c for c in body["classes"]
             if c["week"] == 8 and c["label"] == "222.702 WS-A"][0]
    assert week8["status"] == "Cancelled"
    week7 = [c for c in body["classes"]
             if c["week"] == 7 and c["label"] == "222.702 WS-A"][0]
    assert week7["staff_id"] == "S12"
    assert week7["start"] == "10:00"      # the shortening exception still applies


def test_no_handover_ever_creates_an_exception(client):
    """Exceptions are for weeks that genuinely depart from the timetable, not
    for papering over its staffing."""
    before = client.get("/api/state").json()["exceptions"]
    for weeks in (None, [1, 2], [12]):
        client.post("/api/reassign", json={
            "course_code": "111.701", "section": "B", "staff_id": "S14",
            "weeks": weeks,
        }).raise_for_status()
    after = client.get("/api/state").json()["exceptions"]
    assert len(after) == len(before)


def test_reassigning_to_an_unknown_person_is_refused(client):
    res = client.post("/api/reassign", json={
        "course_code": "333.703", "section": "A", "staff_id": "NOPE",
    })
    assert res.status_code == 400
