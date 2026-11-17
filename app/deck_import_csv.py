import io
import csv

def read_deck_csv(content: bytes) -> list[tuple[int, list[str], bool]]:
    if len(content) > 2 * 1024 * 1024:
        raise ValueError("File exceeds 2 MiB limit")

    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError("Invalid UTF-8 encoding")

    if not text.strip():
        raise ValueError("Empty file provided")

    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
        delimiter = dialect.delimiter
    except csv.Error:
        pass
    else:
        if delimiter in [',', ';', '\t']:
            return _parse_with_delimiter(text, delimiter)

    candidates = []
    for delim in [',', ';', '\t']:
        try:
            reader = csv.reader(io.StringIO(text, newline=''), delimiter=delim, strict=True)
            first = next((row for row in reader if any(c.strip() for c in row)), [])
            candidates.append((len(first), delim))
        except csv.Error:
            continue
    if not candidates:
        raise ValueError("Could not detect valid CSV delimiter")
    return _parse_with_delimiter(text, max(candidates, key=lambda item: item[0])[1])

def _parse_with_delimiter(text: str, delimiter: str) -> list[tuple[int, list[str], bool]]:
    try:
        return _parse_records(text, delimiter)
    except csv.Error as exc:
        raise ValueError("Malformed CSV file") from exc


def _parse_records(text: str, delimiter: str) -> list[tuple[int, list[str], bool]]:
    reader = csv.reader(io.StringIO(text, newline=''), delimiter=delimiter, strict=True)
    records = []
    row_count = 0
    max_cols = 20

    for row in reader:
        row_count += 1
        if row_count > 1000:
            raise ValueError("Exceeded maximum record limit of 1000")
        if len(row) > max_cols:
            raise ValueError(f"Row {row_count} exceeds maximum column count of {max_cols}")
        padded_row = row + [''] * (max_cols - len(row))
        records.append((row_count, padded_row[:8], False))

    if not records:
        raise ValueError("No valid records found")

    if row_count > 1000:
        raise ValueError(f"Exceeded maximum record limit of 1000 (found {row_count})")

    return records
