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
        "course_title": "Design Studio",
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
    assert rows[0]["course_title"] == "Design"


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
