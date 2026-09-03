"""Tests for storage and the HTTP layer.

The engine has its own suite. These check that data survives a round trip
through SQLite unchanged, and that the API does what the interface expects,
including refusing the writes it is supposed to refuse.
"""

import importlib

import pytest
from fastapi.testclient import TestClient

import engine
import importer
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
    weeks, staff, timetable, exceptions, assignments, courses = store.load_all(conn, seed.TERM)
    assert len(weeks) == 12
    assert len(staff) == len(seed.STAFF)
    assert len(timetable) == len(seed.TIMETABLE)
    assert len(exceptions) == len(seed.EXCEPTIONS)
    assert assignments

    classes = engine.expand(timetable, exceptions, assignments, courses)
    assert engine.find_clashes(classes) == []
    assert engine.validate(weeks, staff, timetable, exceptions, assignments, courses) == []


def test_the_sample_data_has_a_gap_to_show(conn):
    seed.load(conn)
    _, _, timetable, exceptions, assignments, courses = store.load_all(conn, seed.TERM)
    cover = engine.coverage(engine.expand(timetable, exceptions, assignments, courses))
    assert 0 < cover.covered < cover.total


def test_one_person_per_class_per_week_is_a_rule_of_the_database(conn):
    seed.load(conn)
    tt = store.get_timetable(conn, seed.TERM)[0]
    store.set_assignment(conn, tt.id, [1], "ahern")
    store.set_assignment(conn, tt.id, [1], "brill")
    held = [a for a in store.get_assignments(conn, seed.TERM) if a.timetable_id == tt.id and a.week == 1]
    assert len(held) == 1
    assert held[0].staff_id == "brill"


def test_removing_a_week_from_a_class_removes_its_staffing(conn):
    seed.load(conn)
    tt = next(r for r in store.get_timetable(conn, seed.TERM) if r.weeks == frozenset(range(1, 13)))
    store.set_assignment(conn, tt.id, [12], "ahern")
    store.save_timetable_row(
        conn,
        {
            "course_code": tt.course_code,
            "section": tt.section, "day": tt.day,
            "start": store.from_time(tt.start), "end": store.from_time(tt.end),
            "weeks": list(range(1, 12)),
        },
        row_id=tt.id,
        term=seed.TERM,
    )
    weeks_held = {a.week for a in store.get_assignments(conn, seed.TERM) if a.timetable_id == tt.id}
    assert 12 not in weeks_held


def test_deleting_a_person_leaves_their_classes_uncovered_not_missing(conn):
    seed.load(conn)
    store.delete_staff(conn, "ahern")
    _, _, timetable, exceptions, assignments, courses = store.load_all(conn, seed.TERM)
    assert all(a.staff_id != "ahern" for a in assignments)
    classes = engine.expand(timetable, exceptions, assignments, courses)
    assert any(c.label == "133150 SHOW-A" and not c.covered for c in classes)


def test_renaming_a_person_carries_their_assignments(conn):
    seed.load(conn)
    store.save_staff(
        conn,
        {"id": "ahern2", "name": "Ahern, Kate", "email": "", "target_minutes": 480},
        original_id="ahern",
    )
    assignments = store.get_assignments(conn, seed.TERM)
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
        if a["timetable_id"] == row_id(client, "133168", "STU-A")
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
    target = row_id(client, "133150", "SHOW-D")
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
    target = row_id(client, "133150", "SHOW-D")
    reply = client.post("/api/assign", json={
        "timetable_id": target, "staff_id": "ahern", "weeks": [1, 2],
    })
    assert reply.status_code == 409
    detail = reply.json()["detail"]
    assert detail["error"] == "double_booked"
    assert "133150 SHOW-A" in detail["message"]
    assert {c["week"] for c in detail["conflicts"]} == {1, 2}

    after = client.get("/api/state").json()
    assert after["problems"] == []
    assert all(
        c["staff_id"] is None
        for c in after["classes"]
        if c["timetable_row_id"] == target
    )


def test_a_refusal_names_the_class_in_the_way(client):
    target = row_id(client, "133150", "SHOW-D")
    detail = client.post("/api/assign", json={
        "timetable_id": target, "staff_id": "brill", "weeks": [4],
    }).json()["detail"]
    conflict = detail["conflicts"][0]
    assert conflict["existing"]["label"] == "133150 SHOW-B"
    assert conflict["proposed"]["label"] == "133150 SHOW-D"
    assert conflict["existing"]["start"] == "14:00"


def test_a_class_can_be_split_between_two_people(client):
    """Half a semester each, which is two sets of weeks rather than two rows."""
    target = row_id(client, "133150", "SHOW-D")
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
    target = row_id(client, "133150", "SHOW-D")
    held = row_id(client, "133150", "SHOW-A")

    assert client.post("/api/assign", json={
        "timetable_id": target, "staff_id": "ahern", "weeks": [1],
    }).status_code == 409

    client.post("/api/unassign", json={"timetable_id": held, "weeks": [1]})

    assert client.post("/api/assign", json={
        "timetable_id": target, "staff_id": "ahern", "weeks": [1],
    }).status_code == 200


def test_taking_over_weeks_somebody_else_holds_needs_saying_so(client):
    target = row_id(client, "133150", "SHOW-A")
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
    target = row_id(client, "133168", "STU-A")
    reply = client.post("/api/assign", json={
        "timetable_id": target, "staff_id": "chen", "weeks": [1, 2, 3],
    })
    assert reply.status_code == 200


def test_assigning_a_week_the_class_does_not_run_is_refused(client):
    target = row_id(client, "133154", "LEC")     # weeks 7, 8, 9 only
    reply = client.post("/api/assign", json={
        "timetable_id": target, "staff_id": "chen", "weeks": [1],
    })
    assert reply.status_code == 400
    assert "does not run" in reply.json()["detail"]


def test_assigning_a_person_who_does_not_exist_is_refused(client):
    reply = client.post("/api/assign", json={
        "timetable_id": row_id(client, "133150", "SHOW-D"), "staff_id": "ghost",
    })
    assert reply.status_code == 400


def test_assigning_with_no_weeks_given_covers_the_whole_run(client):
    target = row_id(client, "133150", "SHOW-D")
    reply = client.post("/api/assign", json={
        "timetable_id": target, "staff_id": "dalzell",
    })
    assert reply.status_code == 200
    assert reply.json()["weeks"] == list(range(1, 13))
    assert client.get("/api/state").json()["coverage"]["percent"] == 100


def test_unassigning_puts_a_class_back_in_the_needs_somebody_list(client):
    target = row_id(client, "133150", "SHOW-A")
    client.post("/api/unassign", json={"timetable_id": target, "weeks": [5]})
    rows = client.get("/api/state").json()["coverage"]["rows"]
    assert any(r["section"] == "SHOW-A" and r["weeks"] == [5] for r in rows)


# ------------------------------------------------------------ availability

def test_availability_marks_the_busy_before_anyone_is_offered(client):
    people = client.post("/api/availability", json={
        "day": "Tuesday", "start": "14:00", "end": "17:00",
        "weeks": list(range(1, 13)),
        "timetable_id": row_id(client, "133150", "SHOW-D"),
    }).json()["staff"]

    by_id = {p["id"]: p for p in people}
    assert not by_id["ahern"]["free"]
    assert by_id["ahern"]["busy_weeks"] == list(range(1, 13))
    assert by_id["dalzell"]["free"]
    assert by_id["ahern"]["minutes"] > 0


# ------------------------------------------------------------ exceptions

def test_an_exception_cannot_carry_staff(client):
    reply = client.post("/api/exceptions", json={
        "week": 3, "course_code": "133150", "section": "SHOW-A",
        "action": "Change", "staff_id": "brill",
    })
    assert reply.status_code == 400
    assert "Assign that week" in reply.json()["detail"]


def test_an_added_class_that_double_books_somebody_is_refused(client):
    reply = client.post("/api/exceptions", json={
        "week": 3, "course_code": "133150", "section": "SHOW-A", "action": "Add",
        "day": "Tuesday", "start": "15:00", "end": "16:00", "staff_id": "ahern",
    })
    assert reply.status_code == 409
    assert reply.json()["detail"]["error"] == "double_booked"


def test_an_added_class_in_a_free_slot_is_allowed(client):
    reply = client.post("/api/exceptions", json={
        "week": 3, "course_code": "133150", "section": "SHOW-A", "action": "Add",
        "day": "Friday", "start": "15:00", "end": "16:00", "staff_id": "ahern",
    })
    assert reply.status_code == 200
    assert client.get("/api/state").json()["problems"] == []


def test_cancelling_a_week_leaves_it_needing_nobody(client):
    before = client.get("/api/state").json()["coverage"]["total"]
    client.post("/api/exceptions", json={
        "week": 4, "course_code": "133150", "section": "SHOW-D", "action": "Cancel",
    })
    assert client.get("/api/state").json()["coverage"]["total"] == before - 1


# ------------------------------------------------------------ import

CSV = (
    b"Course Code,Section,Day,Start,End,Weeks\n"
    b"133150,SHOW-A,Tuesday,14:00,17:00,1-12\n"
    b"999999,X,Friday,9:00,11:00,\"1-4, 6\"\n"
)


def test_import_preview_writes_nothing(client):
    before = client.get("/api/state").json()
    preview = client.post(
        "/api/import/preview", files={"file": ("t.csv", CSV, "text/csv")}
    ).json()

    assert len(preview["rows"]) == 2
    assert preview["issues"] == []
    assert preview["replacing"] == len(before["timetable"])
    assert any(d["course_code"] == "133154" for d in preview["would_drop"])
    assert client.get("/api/state").json()["timetable"] == before["timetable"]


def test_import_keeps_the_staffing_that_still_fits(client):
    preview = client.post(
        "/api/import/preview", files={"file": ("t.csv", CSV, "text/csv")}
    ).json()
    result = client.post(
        "/api/import/commit", json={"rows": preview["rows"], "mode": "replace"}
    ).json()

    assert result["added"] == 2
    assert result["kept"] == 12          # 133150 SHOW-A survives, week for week
    assert result["dropped"]

    after = client.get("/api/state").json()
    assert {r["course_code"] for r in after["timetable"]} == {"133150", "999999"}
    kept = [c for c in after["classes"] if c["label"] == "133150 SHOW-A"]
    assert {c["staff_id"] for c in kept} == {"ahern"}


def test_import_reports_the_rows_it_could_not_read(client):
    bad = (
        b"Course Code,Section,Day,Start,End,Weeks\n"
        b"133150,A,Funday,14:00,17:00,1-12\n"
        b"133154,B,Monday,10:00,12:00,1-4\n"
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
        "course_code": "999.999", "section": "X",
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
    target = row_id(client, "133150", "SHOW-A")
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


# ------------------------------------------------------------ the catalogue

COURSE_CSV = (
    b"Course Code,Academic Year,Semester,Occurrence,Course Name,College,"
    b"Primary Programme,Course Coordinator,Course Coordinator Email,"
    b"Offering Coordinator,Offering Coordinator Email,Grade Reviewer,"
    b"Grade Reviewer Email,Offering Department\n"
    b"144001,2027,S2FS,WLGI,A Course Of My Own,CCA,,Andre Ktori,"
    b"A.Ktori@massey.ac.nz,Dave Carter,D.Carter1@massey.ac.nz,,,MU00693\n"
    b"133150,2027,S2FS,WLGI,Live Music Showcases Renamed,CCA,,Someone,"
    b"s@x.ac.nz,Someone,s@x.ac.nz,,,MU00693\n"
)


def upload(client, path, data, name="courses.csv"):
    return client.post(path, files={"file": (name, data, "text/csv")})


def test_the_sample_catalogue_is_bigger_than_the_timetable(conn):
    seed.load(conn)
    courses = store.get_courses(conn)
    timetabled = {r.course_code for r in store.get_timetable(conn, seed.TERM)}
    assert len(courses) > len(timetabled)
    assert {c.code for c in courses} > timetabled


def test_state_carries_the_catalogue_and_the_offering_being_planned(client):
    body = client.get("/api/state").json()
    assert len(body["courses"]) == len(seed.COURSES)
    assert body["settings"] == {"academic_year": "2027", "semester": "S2FS"}
    assert body["issues"] == []


def test_classes_take_their_name_from_the_catalogue(client):
    classes = client.get("/api/state").json()["classes"]
    showcase = next(c for c in classes if c["course_code"] == "133150")
    assert showcase["course_title"] == "Live Music Showcases"


def test_renaming_a_course_renames_its_classes(client):
    rows = upload(client, "/api/courses/import/preview", COURSE_CSV).json()["rows"]
    client.post("/api/courses/import/commit", json={"rows": rows, "mode": "merge"})

    classes = client.get("/api/state").json()["classes"]
    showcase = next(c for c in classes if c["course_code"] == "133150")
    assert showcase["course_title"] == "Live Music Showcases Renamed"


def test_a_course_import_preview_writes_nothing(client):
    before = client.get("/api/state").json()["courses"]
    preview = upload(client, "/api/courses/import/preview", COURSE_CSV).json()

    assert len(preview["rows"]) == 2
    assert preview["issues"] == []
    assert preview["new"] == 1                     # 144001 is not held yet
    assert preview["updating"] == 1                # 133150 2027 S2FS WLGI is
    assert preview["semesters"] == ["S2FS"]
    assert client.get("/api/state").json()["courses"] == before


def test_merging_updates_in_place_rather_than_doubling_up(client):
    rows = upload(client, "/api/courses/import/preview", COURSE_CSV).json()["rows"]
    first = client.post("/api/courses/import/commit",
                        json={"rows": rows, "mode": "merge"}).json()
    assert first["added"] == 1 and first["updated"] == 1

    again = client.post("/api/courses/import/commit",
                        json={"rows": rows, "mode": "merge"}).json()
    assert again["added"] == 0 and again["updated"] == 2
    assert again["total"] == first["total"]        # importing twice changes nothing


def test_replacing_the_catalogue_clears_what_is_not_in_the_file(client):
    rows = upload(client, "/api/courses/import/preview", COURSE_CSV).json()["rows"]
    result = client.post("/api/courses/import/commit",
                         json={"rows": rows, "mode": "replace_all"}).json()
    assert result["total"] == 2
    assert result["removed"] == len(seed.COURSES) - 1   # 133150 was re-imported

    codes = {c["code"] for c in client.get("/api/state").json()["courses"]}
    assert codes == {"144001", "133150"}


def test_a_timetable_left_without_its_course_says_so(client):
    """Replacing the catalogue can strand a class. That must not be silent."""
    rows = upload(client, "/api/courses/import/preview", COURSE_CSV).json()["rows"]
    client.post("/api/courses/import/commit", json={"rows": rows, "mode": "replace_all"})

    state = client.get("/api/state").json()
    assert any("133154: not in the course list" in i for i in state["issues"])
    orphan = next(c for c in state["classes"] if c["course_code"] == "133154")
    assert orphan["course_title"] == ""
    assert orphan["staff_id"]                       # staffing is untouched


def test_importing_no_courses_is_refused(client):
    assert client.post("/api/courses/import/commit", json={"rows": []}).status_code == 400


def test_switching_term_switches_the_whole_plan(client):
    """A term holds its own calendar, timetable and staffing. The catalogue does
    not: a course keeps its name whichever semester you are planning."""
    before = client.get("/api/state").json()
    assert before["settings"] == {"academic_year": "2027", "semester": "S2FS"}
    assert before["weeks"] and before["timetable"]

    client.put("/api/settings", json={"academic_year": "2028", "semester": "S1FS"})
    empty = client.get("/api/state").json()
    assert empty["weeks"] == [] and empty["timetable"] == []
    assert empty["courses"]                       # the catalogue is not term scoped
    assert {(t["academic_year"], t["semester"]) for t in empty["terms"]} >= {
        ("2027", "S2FS"), ("2028", "S1FS"),
    }

    client.put("/api/settings", json={"academic_year": "2027", "semester": "S2FS"})
    back = client.get("/api/state").json()
    assert len(back["timetable"]) == len(before["timetable"])
    assert back["coverage"] == before["coverage"]


def test_a_course_can_be_removed(client):
    client.delete("/api/courses/666.706",
                  params={"academic_year": "2026", "semester": "S2FS",
                          "occurrence": "WLGI"})
    codes = {c["code"] for c in client.get("/api/state").json()["courses"]}
    assert "666.706" not in codes


# ------------------------------------------------------------ the usual week

def test_state_carries_each_persons_shape(client):
    shapes = {s["staff_id"]: s for s in client.get("/api/state").json()["shapes"]}
    assert set(shapes) == {s[0] for s in seed.STAFF}

    # Brill teaches one week, twelve times.
    assert shapes["brill"]["settled"]
    assert shapes["brill"]["usual_weeks"] == list(range(1, 13))
    assert len(shapes["brill"]["usual"]) == 2

    # Ahern is the same every week but eleven, where a crit is added.
    ahern = shapes["ahern"]
    assert not ahern["settled"]
    assert [d["weeks"] for d in ahern["departures"]] == [[11]]
    assert len(ahern["departures"][0]["added"]) == 1

    # Edmond loses a workshop to Labour Day, in the last teaching week.
    edmond = shapes["edmond"]
    assert [d["weeks"] for d in edmond["departures"]] == [[12]]
    assert edmond["departures"][0]["cancelled"][0]["label"] == "133154 WS-A"

    # Dalzell is the awkward one: a move, then two changes of load.
    assert [d["weeks"] for d in shapes["dalzell"]["departures"]] == [
        [5], [7, 8, 9], [10, 11, 12],
    ]
    assert len(shapes["dalzell"]["departures"][0]["moved"]) == 1


# ------------------------------------------------------------ sample data

TWO_SEMESTERS = (
    b"Course Code,Course Name,Academic Year,Semester,Occurrence\n"
    b"133150,Live Music Showcases,2027,S2FS,WLGI\n"
    b"133167,Music Entrepreneurship 1,2027,S1FS,WLGI\n"
)


def test_the_sample_is_the_real_courses(conn):
    seed.load(conn)
    courses = {c.code: c for c in store.get_courses(conn)}
    assert set(courses) == {"133150", "133154", "133167", "133168", "133175"}
    assert courses["133154"].name == "Music, People, Places"
    assert courses["133150"].coordinator == "Andre Ktori"

    # Labour Day falls on the Monday of the last teaching week.
    weeks = {w.number: w for w in store.get_weeks(conn, seed.TERM)}
    assert weeks[12].starts.isoformat() == "2027-10-25"
    assert "Labour Day" in weeks[12].note


def test_a_coordinator_is_never_a_teacher(conn):
    """The distinction the whole catalogue rests on."""
    seed.load(conn)
    _, staff, timetable, exceptions, assignments, courses = store.load_all(conn, seed.TERM)
    classes = engine.expand(timetable, exceptions, assignments, courses)

    coordinators = {c.coordinator for c in courses} | {c.offering_coordinator for c in courses}
    teaching = engine.teachers_for(classes)
    names = {s.name for s in staff}

    assert coordinators                      # there are some
    assert not (coordinators & names)        # and none of them is staff
    assert set(teaching) == {"133150", "133154", "133168"}
    # Dave Carter coordinates 133168; other people teach it.
    assert "Carter" in next(c for c in courses if c.code == "133168").coordinator
    assert teaching["133168"] == ["brill", "chen", "dalzell"]


def test_everything_the_sample_writes_is_flagged_as_sample(conn):
    seed.load(conn)
    assert store.has_sample(conn)
    for table in store.SAMPLE_TABLES:
        held = conn.execute(f"SELECT COUNT(*), SUM(is_sample) FROM {table}").fetchone()
        assert held[0] > 0 and held[1] == held[0], table


def test_a_cleared_database_stays_cleared_across_a_restart(conn):
    """The bug: is_empty() asked whether the timetable was empty, so clearing
    the sample and restarting brought it straight back."""
    seed.load(conn)
    seed.clear(conn)
    assert not store.is_new(conn)              # a restart would not re-seed

    if store.is_new(conn):                     # simulate app start
        seed.load(conn)
    assert store.get_courses(conn) == []
    assert store.get_timetable(conn, seed.TERM) == []


def test_a_catalogue_imported_before_any_timetable_is_not_overwritten(conn):
    """The same bug, the way it would actually bite: courses in, timetable not yet."""
    seed.clear(conn)
    rows, _ = importer.parse_courses("c.csv", TWO_SEMESTERS)
    store.save_courses(conn, rows)

    assert not store.is_new(conn)
    if store.is_new(conn):
        seed.load(conn)
    assert {c.code for c in store.get_courses(conn)} == {"133150", "133167"}


def test_removing_the_sample_leaves_imported_courses_standing(client):
    rows = upload(client, "/api/courses/import/preview", TWO_SEMESTERS).json()["rows"]
    client.post("/api/courses/import/commit", json={"rows": rows, "mode": "merge"})

    assert client.get("/api/state").json()["has_sample"]
    client.delete("/api/sample-data")

    state = client.get("/api/state").json()
    assert not state["has_sample"]
    # 133150 and 133167 were imported over, so they are the user's now and stay;
    # the three the user never touched go with the sample.
    assert {c["code"] for c in state["courses"]} == {"133150", "133167"}
    assert state["staff"] == []
    assert state["timetable"] == []
    assert state["settings"] == {"academic_year": "", "semester": ""}


def test_importing_over_a_sample_row_makes_it_yours(conn):
    seed.load(conn)
    rows, _ = importer.parse_courses("c.csv", TWO_SEMESTERS)
    store.save_courses(conn, rows)

    flags = dict(conn.execute("SELECT code, is_sample FROM courses"))
    assert flags["133150"] == 0 and flags["133167"] == 0     # imported
    assert flags["133154"] == 1 and flags["133168"] == 1     # untouched


def test_editing_a_sample_record_makes_it_yours(client):
    target = row_id(client, "133150", "SHOW-A")
    client.put(f"/api/timetable/{target}", json={
        "course_code": "133150", "section": "SHOW-A", "day": "Tuesday",
        "start": "14:00", "end": "17:00", "weeks": list(range(1, 13)),
    })
    client.delete("/api/sample-data")
    remaining = {r["section"] for r in client.get("/api/state").json()["timetable"]}
    assert remaining == {"SHOW-A"}


def test_clear_everything_still_takes_the_lot(client):
    client.delete("/api/all-data")
    state = client.get("/api/state").json()
    assert state["courses"] == [] and state["timetable"] == [] and state["staff"] == []
    assert not state["has_sample"]


# ------------------------------------------------------------ import modes

def test_replacing_one_semester_leaves_the_others_alone(client):
    """An export is usually one semester of a bigger catalogue."""
    one = (
        b"Course Code,Course Name,Academic Year,Semester,Occurrence\n"
        b"144001,Something New,2027,S2FS,WLGI\n"
    )
    preview = upload(client, "/api/courses/import/preview", one).json()
    assert preview["offerings"] == [{"academic_year": "2027", "semester": "S2FS"}]
    assert preview["offering_holds"] == 3            # the three S2FS sample courses

    client.post("/api/courses/import/commit",
                json={"rows": preview["rows"], "mode": "replace_offering"})

    held = {(c["code"], c["semester"]) for c in client.get("/api/state").json()["courses"]}
    assert held == {("144001", "S2FS"), ("133167", "S1FS"), ("133175", "S1FS")}


def test_replacing_a_semester_refreshes_every_semester_the_file_covers(client):
    preview = upload(client, "/api/courses/import/preview", TWO_SEMESTERS).json()
    assert [o["semester"] for o in preview["offerings"]] == ["S1FS", "S2FS"]

    client.post("/api/courses/import/commit",
                json={"rows": preview["rows"], "mode": "replace_offering"})
    assert {c["code"] for c in client.get("/api/state").json()["courses"]} == {
        "133150", "133167",
    }


def test_an_unknown_import_mode_is_refused(client):
    rows = upload(client, "/api/courses/import/preview", TWO_SEMESTERS).json()["rows"]
    reply = client.post("/api/courses/import/commit",
                        json={"rows": rows, "mode": "obliterate"})
    assert reply.status_code == 400


def test_state_says_who_teaches_each_course(client):
    teaching = client.get("/api/state").json()["teaching"]
    assert teaching["133150"] == ["ahern", "brill", "chen"]   # not SHOW-D, nobody has it
    assert "133167" not in teaching                            # not timetabled


# ------------------------------------------------------------ terms

def test_two_terms_hold_separate_calendars_without_colliding(conn):
    """Week 1 exists in both and means different dates. It could not before."""
    seed.load(conn)
    other = ("2028", "S1FS")
    store.replace_weeks(conn, [
        {"number": 1, "starts": "2028-02-21", "ends": "2028-02-27", "note": ""},
        {"number": 2, "starts": "2028-02-28", "ends": "2028-03-05", "note": ""},
    ], term=other)
    store.save_timetable_row(conn, {
        "course_code": "133167", "section": "LEC", "day": "Monday",
        "start": "09:00", "end": "10:00", "weeks": [1, 2],
    }, term=other)

    assert len(store.get_weeks(conn, seed.TERM)) == 12
    assert len(store.get_weeks(conn, other)) == 2
    assert store.get_weeks(conn, seed.TERM)[0].starts.isoformat() == "2027-07-26"
    assert store.get_weeks(conn, other)[0].starts.isoformat() == "2028-02-21"
    assert len(store.get_timetable(conn, other)) == 1
    assert store.get_assignments(conn, other) == []      # nothing staffed there yet
    assert len(store.get_assignments(conn, seed.TERM)) > 0
    assert set(store.terms(conn)) >= {seed.TERM, other}


def test_a_database_from_before_terms_keeps_everything(tmp_path):
    """The migration rebuilds weeks and tags rows with the term in settings."""
    old = store.connect(tmp_path / "old.db")
    old.executescript("""
        CREATE TABLE weeks (
            number INTEGER PRIMARY KEY, starts TEXT NOT NULL,
            ends TEXT NOT NULL, note TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '');
        CREATE TABLE timetable (
            id INTEGER PRIMARY KEY AUTOINCREMENT, course_code TEXT NOT NULL,
            section TEXT NOT NULL, day TEXT NOT NULL,
            start TEXT NOT NULL, end TEXT NOT NULL
        );
        INSERT INTO weeks (number, starts, ends, note)
            VALUES (1, '2027-07-26', '2027-08-01', 'first week');
        INSERT INTO settings (key, value)
            VALUES ('academic_year', '2027'), ('semester', 'S2FS');
        INSERT INTO timetable (course_code, section, day, start, end)
            VALUES ('133150', 'SHOW-A', 'Tuesday', '14:00', '17:00');
    """)
    old.commit()

    store.init(old)

    weeks = store.get_weeks(old, ("2027", "S2FS"))
    assert [w.number for w in weeks] == [1]
    assert weeks[0].note == "first week"                 # nothing lost
    rows = store.get_timetable(old, ("2027", "S2FS"))
    assert [r.label for r in rows] == ["133150 SHOW-A"]
    assert store.get_weeks(old, ("", "")) == []          # tagged, not stranded
    old.close()


# ------------------------------------------------------------ the week wizard

def test_a_calendar_is_generated_from_how_people_describe_a_semester(client):
    reply = client.post("/api/weeks/generate", json={
        "first_monday": "2028-02-21", "count": 12,
        "breaks": [{"starts": "2028-04-03", "ends": "2028-04-14"}],
    })
    assert reply.status_code == 200

    weeks = client.get("/api/state").json()["weeks"]
    assert [w["number"] for w in weeks] == list(range(1, 13))
    assert weeks[0]["starts"] == "2028-02-21"
    assert any("Break follows" in w["note"] for w in weeks)
    # the break is a gap, not an extra week
    assert weeks[6]["starts"] > weeks[5]["ends"]


def test_generating_a_calendar_replaces_only_its_own_term(client):
    before = len(client.get("/api/state").json()["timetable"])
    client.post("/api/weeks/generate", json={"first_monday": "2027-07-26", "count": 6})

    state = client.get("/api/state").json()
    assert len(state["weeks"]) == 6
    assert len(state["timetable"]) == before        # the plan is untouched

    client.put("/api/settings", json={"academic_year": "2028", "semester": "S1FS"})
    client.post("/api/weeks/generate", json={"first_monday": "2028-02-21", "count": 4})
    assert len(client.get("/api/state").json()["weeks"]) == 4

    client.put("/api/settings", json={"academic_year": "2027", "semester": "S2FS"})
    assert len(client.get("/api/state").json()["weeks"]) == 6


def test_a_calendar_the_tool_cannot_build_is_refused(client):
    assert client.post("/api/weeks/generate", json={
        "first_monday": "2027-07-26", "count": 0}).status_code == 400
    assert client.post("/api/weeks/generate", json={
        "first_monday": "not a date", "count": 12}).status_code == 400
    assert client.post("/api/weeks/generate", json={
        "first_monday": "2027-07-26", "count": 12,
        "breaks": [{"starts": "2027-09-17", "ends": "2027-09-06"}]}).status_code == 400
