"""Writing the spreadsheets this tool hands out.

The counterpart to importer.py, which reads them. The header row is built from
importer.TIMETABLE_COLUMNS, so a file written here is always one that module can
read back: a template whose columns the parser rejects would be worse than no
template at all.

Two of the columns an export carries are not part of the format. A course name
and who is teaching are there to be read, and the parser ignores them on the way
back in. Staffing is decided in the Planner, where every assignment is checked
against everything else that person teaches; a spreadsheet is not going to be a
second way in past that check.
"""

from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import importer

READ_ONLY = ("Course Name", "Assigned")

WIDTHS = {
    "Course Code": 13, "Section": 12, "Day": 12, "Start": 8, "End": 8,
    "Weeks": 20, "Course Name": 30, "Assigned": 46,
}

FILL_IN = (Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1B2432"))
LEAVE_BE = (Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="7A8598"))

EXAMPLES = [
    ("133150", "SHOW-A", "Tuesday", "14:00", "17:00", "1-12"),
    ("133154", "LEC", "Monday", "09:00", "10:00", "7-9"),
    ("133154", "WS-A", "Monday", "10:00", "12:00", "1-6, 8, 10-12"),
]

NOTES = [
    "One row per class. A course with four sections is four rows.",
    "",
    "Weeks     1-12, or 1-6, 8, 10-12. A break is a gap, not an extra week.",
    "Day       Monday, or Mon. Times as 14:00, 2pm or 1430.",
    "Section   whatever your timetable calls it: LEC, WS-A, SHOW-B.",
    "",
    "Course names are not read from this file. They come from the course",
    "catalogue on the Courses page, so a course is named in one place.",
    "",
    "Who teaches a class is not read from this file either. That is decided",
    "on the Planner, where every assignment is checked against everything",
    "else that person already teaches.",
]


def _header(sheet, columns: tuple[str, ...]) -> None:
    sheet.append(list(columns))
    for index, name in enumerate(columns, start=1):
        cell = sheet.cell(row=1, column=index)
        cell.font, cell.fill = LEAVE_BE if name in READ_ONLY else FILL_IN
        cell.alignment = Alignment(horizontal="left")
        sheet.column_dimensions[get_column_letter(index)].width = WIDTHS.get(name, 16)
    sheet.freeze_panes = "A2"


def _bytes(book: Workbook) -> bytes:
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def timetable_template() -> bytes:
    """A blank timetable to fill in, and a second sheet showing how."""
    book = Workbook()

    sheet = book.active
    sheet.title = "Timetable"
    _header(sheet, importer.TIMETABLE_COLUMNS)

    # Worked rows live on their own sheet so nothing illustrative can be
    # imported by accident along with the real thing.
    example = book.create_sheet("Example")
    _header(example, importer.TIMETABLE_COLUMNS)
    for row in EXAMPLES:
        example.append(list(row))

    example.append([])
    for line in NOTES:
        example.append([line])

    return _bytes(book)


def timetable_export(rows: list[dict]) -> bytes:
    """The current timetable, editable in Excel and importable again.

    Each row wants course_code, section, day, start, end, weeks, and optionally
    course_name and assigned, the latter a list of {name, weeks}.
    """
    book = Workbook()
    sheet = book.active
    sheet.title = "Timetable"
    _header(sheet, importer.TIMETABLE_COLUMNS + READ_ONLY)

    for row in rows:
        sheet.append([
            row.get("course_code", ""),
            row.get("section", ""),
            row.get("day", ""),
            row.get("start", ""),
            row.get("end", ""),
            importer.format_weeks(row.get("weeks") or []),
            row.get("course_name", ""),
            "; ".join(
                f"{span['name']} {importer.format_weeks(span['weeks'])}"
                for span in row.get("assigned") or []
            ),
        ])

    return _bytes(book)
