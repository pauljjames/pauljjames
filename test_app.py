"""Tests for storage and the HTTP layer.

The engine has its own suite. These check that data survives a round trip
through SQLite unchanged, and that the API does what the interface expects,
including refusing the writes it is supposed to refuse.
"""

import importlib

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


def row_id(client, code, section) -> int:
    """The timetable row for a course and section, as the interface would find it."""
    timetable = client.get("/api/state").json()["timetable"]
    return next(
        r["id"] for r in timetable
        if r["course_code"] == code and r["section"] == section
    )


# ------------------------------------------------------------ storage

def test_seed_survives_a_round_trip(conn):
    seed.load(conn)
    weeks, staff, timetable, exceptions, assignments = store.load_all(conn)
    assert len(weeks) == 12
    assert len(staff) == len(seed.STAFF)
    assert len(timetable) == len(seed.TIMETABLE)
    assert len(exceptions) == len(seed.EXCEPTIONS)
    assert assignments

    classes = engine.expand(timetable, exceptions, assignments)
    assert engine.find_clashes(classes) == []
    assert engine.validate(weeks, staff, timetable, exceptions, assignments) == []


def test_the_sample_data_has_a_gap_to_show(conn):
    seed.load(conn)
    _, _, timetable, exceptions, assignments = store.load_all(conn)
    cover = engine.coverage(engine.expand(timetable, exceptions, assignments))
    assert 0 < cover.covered < cover.total


def test_one_person_per_class_per_week_is_a_rule_of_the_database(conn):
    seed.load(conn)
    tt = store.get_timetable(conn)[0]
    store.set_assignment(conn, tt.id, [1], "ahern")
    store.set_assignment(conn, tt.id, [1], "brill")
    held = [a for a in store.get_assignments(conn) if a.timetable_id == tt.id and a.week == 1]
    assert len(held) == 1
    assert held[0].staff_id == "brill"


def test_removing_a_week_from_a_class_removes_its_staffing(conn):
    seed.load(conn)
    tt = next(r for r in store.get_timetable(conn) if r.weeks == frozenset(range(1, 13)))
    store.set_assignment(conn, tt.id, [12], "ahern")
    store.save_timetable_row(
        conn,
        {
            "course_code": tt.course_code, "course_title": tt.course_title,
            "section": tt.section, "day": tt.day,
            "start": store.from_time(tt.start), "end": store.from_time(tt.end),
            "weeks": list(range(1, 12)),
        },
        row_id=tt.id,
    )
    weeks_held = {a.week for a in store.get_assignments(conn) if a.timetable_id == tt.id}
    assert 12 not in weeks_held


def test_deleting_a_person_leaves_their_classes_uncovered_not_missing(conn):
    seed.load(conn)
    store.delete_staff(conn, "ahern")
    _, _, timetable, exceptions, assignments = store.load_all(conn)
    assert all(a.staff_id != "ahern" for a in assignments)
    classes = engine.expand(timetable, exceptions, assignments)
    assert any(c.label == "111.701 A" and not c.covered for c in classes)


def test_renaming_a_person_carries_their_assignments(conn):
    seed.load(conn)
    store.save_staff(
        conn,
        {"id": "ahern2", "name": "Ahern, Kate", "email": "", "target_minutes": 480},
        original_id="ahern",
    )
    assignments = store.get_assignments(conn)
    assert any(a.staff_id == "ahern2" for a in assignments)
    assert all(a.staff_id != "ahern" for a in assignments)


# ------------------------------------------------------------ state

def test_state_reports_coverage_and_staffing(client):
    body = client.get("/api/state").json()
    assert body["coverage"]["total"] > body["coverage"]["covered"] > 0
    assert body["coverage"]["rows"]
    assert body["assignments"]
    assert body["problems"] == []
    assert body["issues"] == []


def test_state_groups_a_split_semester_into_spans(client):
    spans = [
        a for a in client.get("/api/state").json()["assignments"]
        if a["timetable_id"] == row_id(client, "222.702", "WS-C")
    ]
    assert len(spans) == 2
    assert {tuple(s["weeks"]) for s in spans} == {
        tuple(range(1, 7)), tuple(range(7, 13))
    }


def test_state_says_who_is_over_their_target(client):
    over = client.get("/api/state").json()["over_target"]
    assert over
    assert all(o["minutes"] > o["target"] for o in over)


# ------------------------------------------------------------ assigning

def test_assigning_a_free_person_works(client):
    target = row_id(client, "111.701", "D")
    reply = client.post("/api/assign", json={
        "timetable_id": target, "staff_id": "dalzell", "weeks": [1, 2, 3],
    })
    assert reply.status_code == 200
    assert reply.json()["weeks"] == [1, 2, 3]

    classes = client.get("/api/state").json()["classes"]
    staffed = [c for c in classes if c["timetable_row_id"] == target and c["week"] <= 3]
    assert {c["staff_id"] for c in staffed} == {"dalzell"}


def test_assigning_somebody_who_is_busy_is_refused(client):
    """The whole point: the write that would create a clash does not happen."""
    target = row_id(client, "111.701", "D")
    reply = client.post("/api/assign", json={
        "timetable_id": target, "staff_id": "ahern", "weeks": [1, 2],
    })
    assert reply.status_code == 409
    detail = reply.json()["detail"]
    assert detail["error"] == "double_booked"
    assert "111.701 A" in detail["message"]
    assert {c["week"] for c in detail["conflicts"]} == {1, 2}

    after = client.get("/api/state").json()
    assert after["problems"] == []
    assert all(
        c["staff_id"] is None
        for c in after["classes"]
        if c["timetable_row_id"] == target
    )


def test_a_refusal_names_the_class_in_the_way(client):
    target = row_id(client, "111.701", "D")
    detail = client.post("/api/assign", json={
        "timetable_id": target, "staff_id": "brill", "weeks": [4],
    }).json()["detail"]
    conflict = detail["conflicts"][0]
    assert conflict["existing"]["label"] == "111.701 B"
    assert conflict["proposed"]["label"] == "111.701 D"
    assert conflict["existing"]["start"] == "14:00"


def test_a_class_can_be_split_between_two_people(client):
    """Half a semester each, which is two sets of weeks rather than two rows."""
    target = row_id(client, "111.701", "D")
    assert client.post("/api/assign", json={
        "timetable_id": target, "staff_id": "dalzell", "weeks": list(range(1, 7)),
    }).status_code == 200
    assert client.post("/api/assign", json={
        "timetable_id": target, "staff_id": "edmond", "weeks": list(range(7, 13)),
    }).status_code == 200

    state = client.get("/api/state").json()
    spans = [a for a in state["assignments"] if a["timetable_id"] == target]
    assert {(a["staff_id"], tuple(a["weeks"])) for a in spans} == {
        ("dalzell", tuple(range(1, 7))),
        ("edmond", tuple(range(7, 13))),
    }
    assert state["coverage"]["percent"] == 100
    assert len(state["timetable"]) == len(seed.TIMETABLE)   # no row was split off


def test_taking_a_class_off_somebody_frees_them_for_it(client):
    target = row_id(client, "111.701", "D")
    held = row_id(client, "111.701", "A")

    assert client.post("/api/assign", json={
        "timetable_id": target, "staff_id": "ahern", "weeks": [1],
    }).status_code == 409

    client.post("/api/unassign", json={"timetable_id": held, "weeks": [1]})

    assert client.post("/api/assign", json={
        "timetable_id": target, "staff_id": "ahern", "weeks": [1],
    }).status_code == 200


def test_taking_over_weeks_somebody_else_holds_needs_saying_so(client):
    target = row_id(client, "111.701", "A")
    first = client.post("/api/assign", json={
        "timetable_id": target, "staff_id": "dalzell", "weeks": [1, 2],
    })
    assert first.status_code == 409
    detail = first.json()["detail"]
    assert detail["error"] == "already_assigned"
    assert [a["staff_id"] for a in detail["already"]] == ["ahern", "ahern"]

    second = client.post("/api/assign", json={
        "timetable_id": target, "staff_id": "dalzell", "weeks": [1, 2],
        "replace": True,
    })
    assert second.status_code == 200
    assert second.json()["replaced"] == [1, 2]


def test_extending_somebodys_own_class_is_not_a_takeover(client):
    target = row_id(client, "222.702", "WS-C")
    reply = client.post("/api/assign", json={
        "timetable_id": target, "staff_id": "chen", "weeks": [1, 2, 3],
    })
    assert reply.status_code == 200


def test_assigning_a_week_the_class_does_not_run_is_refused(client):
    target = row_id(client, "222.702", "LEC")     # weeks 7, 8, 9 only
    reply = client.post("/api/assign", json={
        "timetable_id": target, "staff_id": "chen", "weeks": [1],
    })
    assert reply.status_code == 400
    assert "does not run" in reply.json()["detail"]


def test_assigning_a_person_who_does_not_exist_is_refused(client):
    reply = client.post("/api/assign", json={
        "timetable_id": row_id(client, "111.701", "D"), "staff_id": "ghost",
    })
    assert reply.status_code == 400


def test_assigning_with_no_weeks_given_covers_the_whole_run(client):
    target = row_id(client, "111.701", "D")
    reply = client.post("/api/assign", json={
        "timetable_id": target, "staff_id": "dalzell",
    })
    assert reply.status_code == 200
    assert reply.json()["weeks"] == list(range(1, 13))
    assert client.get("/api/state").json()["coverage"]["percent"] == 100


def test_unassigning_puts_a_class_back_in_the_needs_somebody_list(client):
    target = row_id(client, "111.701", "A")
    client.post("/api/unassign", json={"timetable_id": target, "weeks": [5]})
    rows = client.get("/api/state").json()["coverage"]["rows"]
    assert any(r["section"] == "A" and r["weeks"] == [5] for r in rows)


# ------------------------------------------------------------ availability

def test_availability_marks_the_busy_before_anyone_is_offered(client):
    people = client.post("/api/availability", json={
        "day": "Tuesday", "start": "14:00", "end": "17:00",
        "weeks": list(range(1, 13)),
        "timetable_id": row_id(client, "111.701", "D"),
    }).json()["staff"]

    by_id = {p["id"]: p for p in people}
    assert not by_id["ahern"]["free"]
    assert by_id["ahern"]["busy_weeks"] == list(range(1, 13))
    assert by_id["dalzell"]["free"]
    assert by_id["ahern"]["minutes"] > 0


# ------------------------------------------------------------ exceptions

def test_an_exception_cannot_carry_staff(client):
    reply = client.post("/api/exceptions", json={
        "week": 3, "course_code": "111.701", "section": "A",
        "action": "Change", "staff_id": "brill",
    })
    assert reply.status_code == 400
    assert "Assign that week" in reply.json()["detail"]


def test_an_added_class_that_double_books_somebody_is_refused(client):
    reply = client.post("/api/exceptions", json={
        "week": 3, "course_code": "111.701", "section": "A", "action": "Add",
        "day": "Tuesday", "start": "15:00", "end": "16:00", "staff_id": "ahern",
    })
    assert reply.status_code == 409
    assert reply.json()["detail"]["error"] == "double_booked"


def test_an_added_class_in_a_free_slot_is_allowed(client):
    reply = client.post("/api/exceptions", json={
        "week": 3, "course_code": "111.701", "section": "A", "action": "Add",
        "day": "Friday", "start": "15:00", "end": "16:00", "staff_id": "ahern",
    })
    assert reply.status_code == 200
    assert client.get("/api/state").json()["problems"] == []


def test_cancelling_a_week_leaves_it_needing_nobody(client):
    before = client.get("/api/state").json()["coverage"]["total"]
    client.post("/api/exceptions", json={
        "week": 4, "course_code": "111.701", "section": "D", "action": "Cancel",
    })
    assert client.get("/api/state").json()["coverage"]["total"] == before - 1


# ------------------------------------------------------------ import

CSV = (
    b"Course Code,Course Title,Section,Day,Start,End,Weeks\n"
    b"111.701,Design Studio,A,Tuesday,14:00,17:00,1-12\n"
    b"999.999,New Course,X,Friday,9:00,11:00,\"1-4, 6\"\n"
)


def test_import_preview_writes_nothing(client):
    before = client.get("/api/state").json()
    preview = client.post(
        "/api/import/preview", files={"file": ("t.csv", CSV, "text/csv")}
    ).json()

    assert len(preview["rows"]) == 2
    assert preview["issues"] == []
    assert preview["replacing"] == len(before["timetable"])
    assert any(d["course_code"] == "222.702" for d in preview["would_drop"])
    assert client.get("/api/state").json()["timetable"] == before["timetable"]


def test_import_keeps_the_staffing_that_still_fits(client):
    preview = client.post(
        "/api/import/preview", files={"file": ("t.csv", CSV, "text/csv")}
    ).json()
    result = client.post(
        "/api/import/commit", json={"rows": preview["rows"], "mode": "replace"}
    ).json()

    assert result["added"] == 2
    assert result["kept"] == 12          # 111.701 A survives, week for week
    assert result["dropped"]

    after = client.get("/api/state").json()
    assert {r["course_code"] for r in after["timetable"]} == {"111.701", "999.999"}
    kept = [c for c in after["classes"] if c["label"] == "111.701 A"]
    assert {c["staff_id"] for c in kept} == {"ahern"}


def test_import_reports_the_rows_it_could_not_read(client):
    bad = (
        b"Course Code,Section,Day,Start,End,Weeks\n"
        b"111.701,A,Funday,14:00,17:00,1-12\n"
        b"222.702,B,Monday,10:00,12:00,1-4\n"
    )
    preview = client.post(
        "/api/import/preview", files={"file": ("t.csv", bad, "text/csv")}
    ).json()
    assert len(preview["rows"]) == 1
    assert any("not a day of the week" in i for i in preview["issues"])


def test_a_file_without_the_columns_we_need_says_so(client):
    reply = client.post(
        "/api/import/preview",
        files={"file": ("t.csv", b"Name,Notes\nfoo,bar\n", "text/csv")},
    )
    assert reply.json()["issues"]
    assert reply.json()["rows"] == []


def test_importing_nothing_is_refused(client):
    assert client.post("/api/import/commit", json={"rows": []}).status_code == 400


def test_append_leaves_the_existing_timetable_alone(client):
    before = len(client.get("/api/state").json()["timetable"])
    rows = [{
        "course_code": "999.999", "course_title": "New", "section": "X",
        "day": "Friday", "start": "09:00", "end": "11:00", "weeks": [1, 2],
    }]
    client.post("/api/import/commit", json={"rows": rows, "mode": "append"})
    assert len(client.get("/api/state").json()["timetable"]) == before + 1


# ------------------------------------------------------------ records

def test_staff_can_be_added_edited_and_removed(client):
    client.post("/api/staff", json={
        "id": "gray", "name": "Gray, Pat", "target_minutes": 300,
    })
    assert any(s["id"] == "gray" for s in client.get("/api/state").json()["staff"])

    client.put("/api/staff/gray", json={
        "id": "gray", "name": "Gray, Patricia", "target_minutes": 240,
    })
    person = next(s for s in client.get("/api/state").json()["staff"] if s["id"] == "gray")
    assert person["name"] == "Gray, Patricia"
    assert person["target_minutes"] == 240

    client.delete("/api/staff/gray")
    assert not any(s["id"] == "gray" for s in client.get("/api/state").json()["staff"])


def test_a_duplicate_staff_id_is_refused(client):
    assert client.post("/api/staff", json={"id": "ahern", "name": "Someone"}).status_code == 409


def test_a_timetable_row_can_be_added_and_removed(client):
    made = client.post("/api/timetable", json={
        "course_code": "555.705", "section": "A", "day": "Friday",
        "start": "09:00", "end": "11:00", "weeks": [1, 2],
    }).json()["id"]
    assert any(r["id"] == made for r in client.get("/api/state").json()["timetable"])

    client.delete(f"/api/timetable/{made}")
    assert not any(r["id"] == made for r in client.get("/api/state").json()["timetable"])


def test_deleting_a_class_takes_its_staffing_with_it(client):
    target = row_id(client, "111.701", "A")
    client.delete(f"/api/timetable/{target}")
    state = client.get("/api/state").json()
    assert all(a["timetable_id"] != target for a in state["assignments"])
    assert state["issues"] == []


def test_sample_data_can_be_reloaded_and_cleared(client):
    client.delete("/api/all-data")
    assert client.get("/api/state").json()["timetable"] == []

    client.post("/api/sample-data")
    state = client.get("/api/state").json()
    assert len(state["timetable"]) == len(seed.TIMETABLE)
    assert state["issues"] == []


def test_the_front_end_is_served(client):
    assert client.get("/").status_code == 200
