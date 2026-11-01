"""Fill the supplied SF4 workbook, retaining its formatting, drawings and print setup.

Only cell contents and workbook sheet registrations change. Inline strings ensure
names beginning with '=' are text, never spreadsheet formulas.
"""
from calendar import month_name
from io import BytesIO
from pathlib import Path
import re
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED

from .schemas import SF4Create

TEMPLATE = Path(__file__).parent / "templates" / "sf4.xlsx"
MOVEMENTS = ("dropout", "transfer_out", "transfer_in")


def set_cell(xml: str, address: str, value) -> str:
    pattern = rf'<c\b([^>]*\br="{address}"[^>]*?)(?:\s*/>|>.*?</c>)'

    def replace(match):
        attrs = re.sub(r'\s+t="[^"]*"', '', match.group(1))
        if isinstance(value, (int, float)):
            return f'<c{attrs}><v>{value}</v></c>'
        return f'<c{attrs} t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>'

    xml, count = re.subn(pattern, replace, xml, count=1, flags=re.DOTALL)
    if not count:
        raise ValueError(f"SF4 template cell missing: {address}")
    return xml


def figures(rows, days):
    def pair(field):
        male = sum(getattr(row, field).male for row in rows)
        female = sum(getattr(row, field).female for row in rows)
        return [male, female, male + female]

    registered, attended = pair("registered"), pair("attendance")
    values = registered + [round(value / days, 2) for value in attended]
    values += [round(attended[i] / (registered[i] * days) * 100, 2) if registered[i] else 0 for i in range(3)]
    for movement in MOVEMENTS:
        previous, current = pair(movement + "_previous"), pair(movement + "_month")
        values += previous + current + [previous[i] + current[i] for i in range(3)]
    return values


def column(number):
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def build_sf4(report: SF4Create) -> bytes:
    output = BytesIO()
    with ZipFile(TEMPLATE) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        base = source.read("xl/worksheets/sheet1.xml").decode("utf-8")
        pages = [report.rows[i:i + 15] for i in range(0, len(report.rows), 15)]
        workbook = source.read("xl/workbook.xml").decode("utf-8")
        relationships = source.read("xl/_rels/workbook.xml.rels").decode("utf-8")
        content_types = source.read("[Content_Types].xml").decode("utf-8")
        # The supplied blank template has a stale external-workbook reference.
        # No cells use it; remove it so generated reports do not request updates.
        workbook = re.sub(r"<externalReferences>.*?</externalReferences>", "", workbook, flags=re.DOTALL)
        relationships = re.sub(r'<Relationship\b[^>]*Type="[^"]*/externalLink"[^>]*/>', "", relationships)
        content_types = re.sub(r'<Override\b[^>]*PartName="/xl/externalLinks/[^"]*"[^>]*/>', "", content_types)
        year, month = map(int, report.month.split("-"))
        for page_index, rows in enumerate(pages, 1):
            xml = base
            headers = {"I4": report.region, "N4": report.division, "Y4": report.district,
                       "C5": report.school_id, "C7": report.school_name, "Y7": report.academic_year,
                       "AJ7": f"{month_name[month]} {year}", "Y39": report.school_head}
            for address, value in headers.items():
                xml = set_cell(xml, address, value)
            for row_index, row in enumerate(rows, 12):
                for col, value in (("A", row.adviser), ("C", row.grade), ("D", row.section)):
                    xml = set_cell(xml, f"{col}{row_index}", value)
                for col, value in enumerate(figures([row], report.school_days), 5):
                    xml = set_cell(xml, f"{column(col)}{row_index}", value)
            grades = ["K", "1", "2", "3", "4", "5", "6"] if report.school_level == "elementary" else [None, "7", "8", "9", "10", "11", "12"]
            for summary_row, grade in enumerate(grades + ["NG", "TOTAL"], 28):
                selected = rows if grade == "TOTAL" else [row for row in rows if row.grade == grade]
                for col, value in enumerate(figures(selected, report.school_days), 5):
                    xml = set_cell(xml, f"{column(col)}{summary_row}", value)
            target.writestr(f"xl/worksheets/sheet{page_index}.xml", xml)
            if page_index > 1:
                target.writestr(f"xl/worksheets/_rels/sheet{page_index}.xml.rels", source.read("xl/worksheets/_rels/sheet1.xml.rels"))
                workbook = workbook.replace("</sheets>", f'<sheet name="SF4 Page {page_index}" sheetId="{page_index}" r:id="sf4Page{page_index}"/></sheets>')
                relationships = relationships.replace("</Relationships>", f'<Relationship Id="sf4Page{page_index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{page_index}.xml"/></Relationships>')
                content_types = content_types.replace("</Types>", f'<Override PartName="/xl/worksheets/sheet{page_index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        replacements = {"xl/workbook.xml": workbook, "xl/_rels/workbook.xml.rels": relationships, "[Content_Types].xml": content_types}
        for item in source.infolist():
            if item.filename == "xl/worksheets/sheet1.xml" or item.filename.startswith("xl/externalLinks/"):
                continue
            target.writestr(item, replacements.get(item.filename, source.read(item.filename)))
    return output.getvalue()
