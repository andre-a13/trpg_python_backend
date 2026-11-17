"""Bounded reader for the Deck worksheet of Google Sheets Excel exports."""
import io
import posixpath
import re
import zipfile
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

from app.deck_import_csv import read_deck_csv


MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
MAX_SIZE = 2 * 1024 * 1024


def _xml(archive: zipfile.ZipFile, path: str) -> ET.Element:
    data = archive.read(path)
    # Excel XML is UTF-8 or UTF-16. Check after removing nulls to cover both.
    normalized = data.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in normalized or b"<!ENTITY" in normalized:
        raise ValueError("DTD/entities are not supported")
    return ET.fromstring(data)


def _styles(archive: zipfile.ZipFile) -> tuple[list[bool], list[str]]:
    if "xl/styles.xml" not in archive.namelist():
        return [False], [""]
    root = _xml(archive, "xl/styles.xml")
    formats = {int(fmt.get("numFmtId", "0")): fmt.get("formatCode", "")
               for fmt in root.findall(f"{MAIN}numFmts/{MAIN}numFmt")}
    fills = []
    for fill in root.findall(f"{MAIN}fills/{MAIN}fill"):
        pattern = fill.find(f"{MAIN}patternFill")
        color = pattern.find(f"{MAIN}fgColor") if pattern is not None else None
        yellow = False
        if color is not None and pattern.get("patternType") == "solid":
            rgb = color.get("rgb", "")[-6:]
            if re.fullmatch(r"[0-9A-Fa-f]{6}", rgb):
                red, green, blue = (int(rgb[i:i + 2], 16) for i in (0, 2, 4))
                yellow = red >= 200 and green >= 170 and blue <= 130
            elif color.get("indexed") in {"6", "13"}:
                yellow = True
        fills.append(yellow)
    styles = []
    style_formats = []
    for xf in root.findall(f"{MAIN}cellXfs/{MAIN}xf"):
        index = int(xf.get("fillId", "0"))
        if index < 0 or index >= len(fills):
            raise ValueError("Invalid fill style")
        styles.append(fills[index])
        style_formats.append(formats.get(int(xf.get("numFmtId", "0")), ""))
    return styles or [False], style_formats or [""]


def _xlsx(content: bytes) -> list[tuple[int, list[str], bool]]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        entries = archive.infolist()
        if (len(entries) > 200 or len({entry.filename for entry in entries}) != len(entries)
                or sum(entry.file_size for entry in entries) > 20 * 1024 * 1024
                or any(entry.flag_bits & 1 for entry in entries)):
            raise ValueError("XLSX archive exceeds limits or contains duplicate/encrypted entries")
        book = _xml(archive, "xl/workbook.xml")
        sheets = book.findall(f"{MAIN}sheets/{MAIN}sheet")
        decks = [sheet for sheet in sheets if sheet.get("name", "").casefold() == "deck"]
        if len(decks) != 1 and len(sheets) != 1:
            raise ValueError("Choose a workbook with a Deck worksheet or a single worksheet")
        sheet = decks[0] if decks else sheets[0]
        relations = _xml(archive, "xl/_rels/workbook.xml.rels")
        relation = next((rel for rel in relations if rel.get("Id") == sheet.get(f"{REL}id")), None)
        if (relation is None or relation.get("TargetMode") == "External"
                or not relation.get("Type", "").endswith("/worksheet")):
            raise ValueError("Invalid worksheet relationship")
        target = relation.get("Target", "")
        path = posixpath.normpath(target.lstrip("/") if target.startswith("/") else posixpath.join("xl", target))
        if not path.startswith("xl/") or "\\" in path or ":" in path:
            raise ValueError("Invalid worksheet path")
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(item.itertext()) for item in _xml(archive, "xl/sharedStrings.xml").findall(f"{MAIN}si")]
        styles, style_formats = _styles(archive)
        properties = book.find(f"{MAIN}workbookPr")
        date1904 = properties is not None and properties.get("date1904") in {"1", "true"}
        root = _xml(archive, path)
        result = []
        seen = set()
        for row in root.findall(f"{MAIN}sheetData/{MAIN}row"):
            number = int(row.get("r", "0"))
            if not 1 <= number <= 1000 or number in seen:
                raise ValueError("Invalid/duplicate worksheet row (maximum 1000)")
            seen.add(number)
            values = [""] * 8
            yellow = False
            columns = set()
            for cell in row.findall(f"{MAIN}c"):
                address = re.fullmatch(r"([A-Z]{1,3})(\d+)", cell.get("r", ""))
                if address is None or int(address[2]) != number:
                    raise ValueError("Invalid cell address")
                column = 0
                for letter in address[1]:
                    column = column * 26 + ord(letter) - 64
                if column > 26 or column in columns:
                    raise ValueError("Invalid/duplicate worksheet column (maximum Z)")
                columns.add(column)
                if column > 8:
                    continue
                style = int(cell.get("s", "0"))
                if not 0 <= style < len(styles):
                    raise ValueError("Invalid cell style")
                formula = cell.find(f"{MAIN}f")
                value = cell.findtext(f"{MAIN}v", "")
                if formula is not None:
                    value = "=" + (formula.text or "")
                elif cell.get("t") == "s":
                    index = int(value)
                    if not 0 <= index < len(strings):
                        raise ValueError("Invalid shared string index")
                    value = strings[index]
                elif cell.get("t") == "inlineStr":
                    value = "".join(t.text or "" for t in cell.findall(f".//{MAIN}t"))
                elif cell.get("t") in {None, "n"} and value:
                    # Google exports integer quantities as 1.0 in native XLSX.
                    try:
                        numeric = Decimal(value)
                        stats_date = re.fullmatch(r"d{1,2}([/-])m{1,2}", style_formats[style]) if column == 5 else None
                        if stats_date and numeric.is_finite() and 0 <= numeric <= 2957000:
                            # Google auto-converts stats like 3/2 into dates.
                            epoch = datetime(1904, 1, 1) if date1904 else datetime(1899, 12, 30)
                            date = epoch + timedelta(days=int(numeric))
                            value = f"{date.day}{stats_date[1]}{date.month}"
                        elif numeric.is_finite() and abs(numeric) <= 10000 and numeric == numeric.to_integral_value():
                            value = str(int(numeric))
                    except InvalidOperation:
                        raise ValueError("Invalid numeric cell") from None
                values[column - 1] = value
                if column == 1:
                    yellow = styles[style]
            result.append((number, values, yellow))
        return sorted(result)


def read_deck_file(filename: str, content: bytes) -> list[tuple[int, list[str], bool]]:
    if not content or len(content) > MAX_SIZE:
        raise ValueError("Choose a nonempty file of at most 2 MiB")
    if filename.lower().endswith(".csv"):
        return read_deck_csv(content)
    if not filename.lower().endswith(".xlsx"):
        raise ValueError("Only CSV and XLSX files are supported")
    try:
        rows = _xlsx(content)
        if not rows:
            raise ValueError("Empty worksheet")
        return rows
    except (zipfile.BadZipFile, ET.ParseError, KeyError, IndexError, OSError, RuntimeError, NotImplementedError) as exc:
        raise ValueError("Invalid XLSX file") from exc
