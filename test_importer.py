"""Importer tests.

The timetable arrives as somebody else's spreadsheet, so these are mostly about
reading what real files contain rather than what we would prefer them to.
"""

import io

import pytest

import importer


def csv_bytes(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode("utf-8")


HEADER = "Course Code,Course Title,Section,Day,Start,End,Weeks"


def test_a_plain_file_reads_straight_through():
    rows, issues = importer.parse("t.csv", csv_bytes(
        HEADER,
        "111.701,Design Studio,A,Tuesday,14:00,17:00,1-12",
    ))
    assert issues == []
    assert rows == [{
        "course_code": "111.701",
        "section": "A",
        "day": "Tuesday",
        "start": "14:00",
        "end": "17:00",
        "weeks": list(range(1, 13)),
    }]


@pytest.mark.parametrize("text,expected", [
    ("1-12", list(range(1, 13))),
    ("1-6, 8", [1, 2, 3, 4, 5, 6, 8]),
    ("7;8;9", [7, 8, 9]),
    ("1 to 3", [1, 2, 3]),
    ("weeks 1-3", [1, 2, 3]),
    ("3", [3]),
    ("1-3 and 5", [1, 2, 3, 5]),
    ("2-4, 3-5", [2, 3, 4, 5]),
])
def test_weeks_are_read_the_way_people_write_them(text, expected):
    rows, issues = importer.parse("t.csv", csv_bytes(
        HEADER, f'111.701,Design,A,Tuesday,14:00,17:00,"{text}"',
    ))
    assert issues == []
    assert rows[0]["weeks"] == expected


@pytest.mark.parametrize("text,expected", [
    ("9:00", "09:00"),
    ("09:00", "09:00"),
    ("9.30", "09:30"),
    ("0900", "09:00"),
    ("9am", "09:00"),
    ("1pm", "13:00"),
    ("1:30pm", "13:30"),
    ("12am", "00:00"),
    ("12pm", "12:00"),
])
def test_times_are_read_the_way_people_write_them(text, expected):
    rows, issues = importer.parse("t.csv", csv_bytes(
        HEADER, f"111.701,Design,A,Tuesday,{text},23:00,1",
    ))
    assert issues == []
    assert rows[0]["start"] == expected


@pytest.mark.parametrize("text,expected", [
    ("Monday", "Monday"),
    ("monday", "Monday"),
    ("Mon", "Monday"),
    ("Tues", "Tuesday"),
    ("Thur", "Thursday"),
    ("Thurs", "Thursday"),
    ("WED", "Wednesday"),
    ("Fri.", "Friday"),
])
def test_days_are_read_the_way_people_write_them(text, expected):
    rows, _ = importer.parse("t.csv", csv_bytes(
        HEADER, f"111.701,Design,A,{text},09:00,10:00,1",
    ))
    assert rows[0]["day"] == expected


def test_headers_are_matched_loosely():
    rows, issues = importer.parse("t.csv", csv_bytes(
        "code,name,activity,weekday,from,to,teaching weeks",
        "111.701,Design,Lecture,Monday,09:00,10:00,1-3",
    ))
    assert issues == []
    assert rows[0]["section"] == "Lecture"


def test_a_missing_column_is_named():
    rows, issues = importer.parse("t.csv", csv_bytes(
        "Course Code,Section,Day", "111.701,A,Monday",
    ))
    assert rows == []
    assert "start" in issues[0] and "end" in issues[0] and "weeks" in issues[0]


def test_a_bad_row_is_left_out_and_the_rest_still_import():
    rows, issues = importer.parse("t.csv", csv_bytes(
        HEADER,
        "111.701,Design,A,Funday,14:00,17:00,1-12",
        "222.702,Materials,B,Monday,10:00,12:00,1-4",
    ))
    assert [r["section"] for r in rows] == ["B"]
    assert "Row 2" in issues[0]


@pytest.mark.parametrize("bad,complaint", [
    ("111.701,Design,A,Monday,17:00,14:00,1-3", "ends at or before it starts"),
    ("111.701,Design,A,Monday,09:00,10:00,", "never run"),
    ("111.701,Design,A,Monday,09:00,10:00,6-2", "backwards"),
    ("111.701,Design,A,Monday,09:00,10:00,soon", "not a week"),
    (",Design,A,Monday,09:00,10:00,1", "no course code"),
    ("111.701,Design,,Monday,09:00,10:00,1", "no section"),
    ("111.701,Design,A,Monday,noon,10:00,1", "not a time"),
])
def test_what_cannot_be_read_is_said_plainly(bad, complaint):
    rows, issues = importer.parse("t.csv", csv_bytes(HEADER, bad))
    assert rows == []
    assert any(complaint in i for i in issues)


def test_the_row_number_matches_the_spreadsheet():
    _, issues = importer.parse("t.csv", csv_bytes(
        HEADER,
        "111.701,Design,A,Monday,09:00,10:00,1",
        "222.702,Materials,B,Funday,09:00,10:00,1",
    ))
    assert issues[0].startswith("Row 3:")


def test_one_section_twice_is_refused_rather_than_duplicated():
    """The failure that made the spreadsheet untrustworthy, caught on the way in."""
    rows, issues = importer.parse("t.csv", csv_bytes(
        HEADER,
        "111.701,Design,A,Monday,09:00,10:00,1-6",
        "111.701,Design,A,Thursday,14:00,17:00,7-12",
    ))
    assert len(rows) == 1
    assert any("also on row 2" in i for i in issues)


def test_blank_lines_are_skipped():
    rows, issues = importer.parse("t.csv", csv_bytes(
        HEADER,
        "111.701,Design,A,Monday,09:00,10:00,1",
        ",,,,,,",
        "222.702,Materials,B,Monday,10:00,12:00,1",
    ))
    assert len(rows) == 2
    assert issues == []


def test_semicolons_and_tabs_are_read_too():
    rows, _ = importer.parse("t.csv", csv_bytes(
        HEADER.replace(",", ";"),
        "111.701;Design;A;Monday;09:00;10:00;1-3",
    ))
    assert rows[0]["weeks"] == [1, 2, 3]


def test_an_empty_file_says_so():
    with pytest.raises(importer.ImportError_):
        importer.parse("t.csv", b"")


def test_rows_come_back_in_a_predictable_order():
    rows, _ = importer.parse("t.csv", csv_bytes(
        HEADER,
        "222.702,Materials,B,Monday,10:00,12:00,1",
        "111.701,Design,B,Monday,09:00,10:00,1",
        "111.701,Design,A,Monday,09:00,10:00,1",
    ))
    assert [(r["course_code"], r["section"]) for r in rows] == [
        ("111.701", "A"), ("111.701", "B"), ("222.702", "B"),
    ]


def test_an_xlsx_file_reads_like_a_csv():
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(HEADER.split(","))
    sheet.append(["111.701", "Design Studio", "A", "Tuesday", "14:00", "17:00", "1-12"])
    buffer = io.BytesIO()
    book.save(buffer)

    rows, issues = importer.parse("timetable.xlsx", buffer.getvalue())
    assert issues == []
    assert rows[0]["course_code"] == "111.701"
    assert rows[0]["weeks"] == list(range(1, 13))


def test_a_spreadsheet_time_cell_is_understood():
    openpyxl = pytest.importorskip("openpyxl")
    from datetime import time

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(HEADER.split(","))
    sheet.append(["111.701", "Design", "A", "Tuesday", time(14, 0), time(17, 0), "1-3"])
    buffer = io.BytesIO()
    book.save(buffer)

    rows, issues = importer.parse("timetable.xlsx", buffer.getvalue())
    assert issues == []
    assert (rows[0]["start"], rows[0]["end"]) == ("14:00", "17:00")


# ------------------------------------------------------------ the catalogue

COURSE_HEADER = (
    "Course Code,Academic Year,Semester,Occurrence,Course Name,College,"
    "Primary Programme,Course Coordinator,Course Coordinator Email,"
    "Offering Coordinator,Offering Coordinator Email,Grade Reviewer,"
    "Grade Reviewer Email,Offering Department"
)


def test_a_real_export_reads_straight_through():
    rows, issues = importer.parse_courses("courses.csv", csv_bytes(
        COURSE_HEADER,
        "133150,2027,S2FS,WLGI,Live Music Showcases,CCA College of Creative Arts,,"
        "Andre Ktori,A.Ktori@massey.ac.nz,Dave Carter,D.Carter1@massey.ac.nz,,,"
        "MU00693 - School of Music and Screen Arts",
    ))
    assert issues == []
    assert rows[0] == {
        "code": "133150",
        "academic_year": "2027",
        "semester": "S2FS",
        "occurrence": "WLGI",
        "name": "Live Music Showcases",
        "college": "CCA College of Creative Arts",
        "programme": "",
        "coordinator": "Andre Ktori",
        "coordinator_email": "A.Ktori@massey.ac.nz",
        "offering_coordinator": "Dave Carter",
        "offering_coordinator_email": "D.Carter1@massey.ac.nz",
        "grade_reviewer": "",
        "grade_reviewer_email": "",
        "department": "MU00693 - School of Music and Screen Arts",
    }


def test_a_course_name_with_a_comma_survives():
    rows, _ = importer.parse_courses("courses.csv", csv_bytes(
        COURSE_HEADER,
        '133154,2027,S2FS,WLGI,"Music, People, Places",CCA,UBCMS,Jon He,'
        'J.He1@massey.ac.nz,Jon He,J.He1@massey.ac.nz,Dana Cameron,'
        'D.Cameron@massey.ac.nz,MU00693',
    ))
    assert rows[0]["name"] == "Music, People, Places"


def test_the_four_coordinator_columns_stay_apart():
    """The bug worth guarding: they all start with the same words."""
    rows, _ = importer.parse_courses("courses.csv", csv_bytes(
        COURSE_HEADER,
        "133154,2027,S2FS,WLGI,Music,CCA,UBCMS,Course Person,course@x.ac.nz,"
        "Offering Person,offering@x.ac.nz,Reviewer Person,reviewer@x.ac.nz,MU00693",
    ))
    row = rows[0]
    assert row["coordinator"] == "Course Person"
    assert row["coordinator_email"] == "course@x.ac.nz"
    assert row["offering_coordinator"] == "Offering Person"
    assert row["offering_coordinator_email"] == "offering@x.ac.nz"
    assert row["grade_reviewer"] == "Reviewer Person"
    assert row["grade_reviewer_email"] == "reviewer@x.ac.nz"


def test_one_code_in_two_semesters_is_two_courses():
    rows, issues = importer.parse_courses("courses.csv", csv_bytes(
        COURSE_HEADER,
        "133150,2027,S1FS,WLGI,Live Music Showcases,CCA,,A,a@x,B,b@x,,,MU00693",
        "133150,2027,S2FS,WLGI,Live Music Showcases,CCA,,A,a@x,B,b@x,,,MU00693",
    ))
    assert issues == []
    assert [r["semester"] for r in rows] == ["S1FS", "S2FS"]


def test_the_same_offering_twice_in_one_file_is_refused():
    rows, issues = importer.parse_courses("courses.csv", csv_bytes(
        COURSE_HEADER,
        "133150,2027,S1FS,WLGI,Live Music Showcases,CCA,,A,a@x,B,b@x,,,MU00693",
        "133150,2027,S1FS,WLGI,Live Music Showcases,CCA,,A,a@x,B,b@x,,,MU00693",
    ))
    assert len(rows) == 1
    assert any("already on row 2" in i for i in issues)


def test_a_row_with_no_course_code_is_left_out():
    rows, issues = importer.parse_courses("courses.csv", csv_bytes(
        COURSE_HEADER,
        ",2027,S1FS,WLGI,Nameless,CCA,,A,a@x,B,b@x,,,MU00693",
    ))
    assert rows == []
    assert any("no course code" in i for i in issues)


def test_a_file_missing_the_code_or_name_column_says_so():
    rows, issues = importer.parse_courses("courses.csv", csv_bytes(
        "Semester,College", "S1FS,CCA",
    ))
    assert rows == []
    assert "code" in issues[0] and "name" in issues[0]


def test_a_numeric_course_code_out_of_a_spreadsheet_stays_a_code():
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(COURSE_HEADER.split(","))
    sheet.append([133150, 2027, "S2FS", "WLGI", "Live Music Showcases", "CCA", "",
                  "Andre Ktori", "A.Ktori@massey.ac.nz", "Dave Carter",
                  "D.Carter1@massey.ac.nz", "", "", "MU00693"])
    buffer = io.BytesIO()
    book.save(buffer)

    rows, issues = importer.parse_courses("courses.xlsx", buffer.getvalue())
    assert issues == []
    assert rows[0]["code"] == "133150"          # not 133150.0, not an int
    assert rows[0]["academic_year"] == "2027"


def test_courses_come_back_in_a_predictable_order():
    rows, _ = importer.parse_courses("courses.csv", csv_bytes(
        COURSE_HEADER,
        "133175,2027,S1FS,WLGI,Music Practice 1,CCA,,A,a@x,B,b@x,,,MU00693",
        "133150,2027,S2FS,WLGI,Live Music Showcases,CCA,,A,a@x,B,b@x,,,MU00693",
        "133150,2027,S1FS,WLGI,Live Music Showcases,CCA,,A,a@x,B,b@x,,,MU00693",
    ))
    assert [(r["code"], r["semester"]) for r in rows] == [
        ("133150", "S1FS"), ("133150", "S2FS"), ("133175", "S1FS"),
    ]
