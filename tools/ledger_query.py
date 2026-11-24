#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only, bounded queries for graph/edges.csv. See ledger_query.md."""

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from pathlib import Path


DEFAULT_LEDGER = Path(__file__).resolve().parent.parent / "graph" / "edges.csv"
VALID_STATUS = ("open", "fixed", "verified", "rejected", "superseded", "deferred")
DEFAULT_COLUMNS = ("id", "status", "severity", "title", "location")
REFERENCE_ID = re.compile(r"(?<![\w-])[FDM]-[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*(?![\w-])")


class LedgerError(ValueError):
    """The ledger or a query parameter is invalid; no partial result is safe."""


def _read_ledger(path):
    """Validate the complete source once, including rows outside the query."""
    path = Path(path).resolve()
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise LedgerError(f"Cannot read ledger {path}: {exc}") from exc
    source = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
              "encoding": "utf-8-sig", "bytes": len(raw)}
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise LedgerError(f"Ledger must be UTF-8: {path} (byte {exc.start})") from exc
    if "\x00" in content:
        raise LedgerError("Invalid CSV: NUL character in source")

    reader = csv.reader(io.StringIO(content, newline=""), strict=True)
    try:
        header = next(reader, None)
        if not header or any(not name.strip() for name in header):
            raise LedgerError("Invalid CSV: missing or empty column name")
        if len(set(header)) != len(header):
            raise LedgerError("Invalid CSV: duplicate column name")
        missing = {"id", "status"} - set(header)
        if missing:
            raise LedgerError("Missing required columns: " + ", ".join(sorted(missing)))
        rows, seen = [], set()
        for values in reader:
            if not values:  # CSV blank lines carry no record.
                continue
            if len(values) != len(header):
                raise LedgerError(f"Invalid CSV at line {reader.line_num}: expected "
                                  f"{len(header)} fields, got {len(values)}")
            row = dict(zip(header, values))
            for name in ("id", "status"):
                if not row[name].strip():
                    raise LedgerError(f"Missing required value '{name}' at line {reader.line_num}")
                if row[name] != row[name].strip():
                    raise LedgerError(f"Whitespace around '{name}' at line {reader.line_num}")
            if row["id"] in seen:
                raise LedgerError(f"Duplicate ID '{row['id']}' at line {reader.line_num}")
            if row["status"] not in VALID_STATUS:
                raise LedgerError(f"Invalid status '{row['status']}' at line {reader.line_num}")
            seen.add(row["id"])
            rows.append(row)
    except csv.Error as exc:
        raise LedgerError(f"Invalid CSV at line {reader.line_num}: {exc}") from exc
    return source, header, rows


def _related_ids(rows, seeds):
    """Follow F/D/M references in both directions, with a visited set for cycles."""
    by_id = {row["id"]: row for row in rows}
    links = {row_id: set() for row_id in by_id}
    for row in rows:
        for name, value in row.items():
            if name == "id":
                continue
            for reference in REFERENCE_ID.findall(value):
                if reference in links:
                    links[row["id"]].add(reference)
                    links[reference].add(row["id"])
    selected, pending = set(seeds), list(seeds)
    while pending:
        for reference in links[pending.pop()]:
            if reference not in selected:
                selected.add(reference)
                pending.append(reference)
    return selected


def query_ledger(ledger_path=DEFAULT_LEDGER, *, ids=None, statuses=None, query=None,
                 related=False, limit=50, offset=0, columns=None):
    """Return projected rows plus source/filter/pagination metadata without writes.

    Filters are ANDed; repeated IDs/statuses are ORed. Without explicit IDs the
    default status is open; explicit IDs without statuses select any status.
    related=True expands the filtered seeds across all statuses before paging.
    """
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise LedgerError("limit must be a positive integer")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise LedgerError("offset must be a nonnegative integer")
    ids = list(dict.fromkeys(ids or []))
    statuses = list(dict.fromkeys(statuses or []))
    if any(not isinstance(row_id, str) or not row_id.strip() for row_id in ids):
        raise LedgerError("IDs must be nonempty strings")
    if any(status not in VALID_STATUS + ("all",) for status in statuses):
        raise LedgerError("Unknown status; use " + ", ".join(VALID_STATUS + ("all",)))
    if "all" in statuses and len(statuses) > 1:
        raise LedgerError("status 'all' cannot be combined with other statuses")
    effective_statuses = statuses or ([] if ids else ["open"])
    if effective_statuses == ["all"]:
        effective_statuses = []
    if query is not None and not isinstance(query, str):
        raise LedgerError("query must be a string")
    needle = (query or "").casefold()
    source, header, rows = _read_ledger(ledger_path)
    if columns is None:
        columns = [name for name in DEFAULT_COLUMNS if name in header]
    else:
        columns = list(dict.fromkeys(["id", "status"] + list(columns)))
        if any(name not in header for name in columns):
            unknown = [name for name in columns if name not in header]
            raise LedgerError("Unknown output columns: " + ", ".join(unknown))

    id_filter, status_filter = set(ids), set(effective_statuses)
    seeds = [row["id"] for row in rows
             if (not id_filter or row["id"] in id_filter)
             and (not status_filter or row["status"] in status_filter)
             and (not needle or any(needle in value.casefold() for value in row.values()))]
    selected = _related_ids(rows, seeds) if related else set(seeds)
    matches = [row for row in rows if row["id"] in selected]
    page = matches[offset:offset + limit]
    has_more = offset + len(page) < len(matches)
    existing_ids = {row["id"] for row in rows}
    return {
        "source": source,
        "filters": {"ids": ids, "statuses": effective_statuses, "query": query or "",
                    "related": bool(related)},
        "related_mode": "undirected-transitive" if related else None,
        "total": len(rows), "seed_count": len(seeds), "matched": len(matches),
        "returned": len(page), "offset": offset, "limit": limit,
        "has_more": has_more, "truncated": bool(offset and matches) or has_more,
        "next_offset": offset + len(page) if has_more else None,
        "missing_ids": [row_id for row_id in ids if row_id not in existing_ids],
        "columns": columns,
        "rows": [{name: row[name] for name in columns} for row in page],
    }


def _md_cell(value):
    # Keep each source value inside one table cell, including HTML-like notes.
    return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\\", "&#92;").replace("|", "&#124;")
            .replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>"))


def render_markdown(result):
    """Render the same metadata and bounded rows without silently losing fields."""
    metadata = {name: value for name, value in result.items() if name != "rows"}
    metadata_json = json.dumps(metadata, ensure_ascii=False, indent=2)
    # A path/search string may contain backticks; choose a non-closing fence.
    longest = max((len(run) for run in re.findall(r"`+", metadata_json)), default=0)
    fence = "`" * max(3, longest + 1)
    lines = [fence + "json", metadata_json, fence, "",
             "| " + " | ".join(_md_cell(name) for name in result["columns"]) + " |",
             "| " + " | ".join("---" for _ in result["columns"]) + " |"]
    lines.extend("| " + " | ".join(_md_cell(row[name]) for name in result["columns"]) + " |"
                 for row in result["rows"])
    return "\n".join(lines)


def _positive(value):
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def _nonnegative(value):
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a nonnegative integer") from exc
    if number < 0:
        raise argparse.ArgumentTypeError("must be a nonnegative integer")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER, help="source CSV path")
    parser.add_argument("--id", dest="ids", action="append", help="exact ID (repeatable)")
    parser.add_argument("--status", dest="statuses", action="append", choices=VALID_STATUS + ("all",),
                        help="status (repeatable); default open, or all when --id is present")
    parser.add_argument("--query", help="case-insensitive literal substring across all fields")
    parser.add_argument("--related", action="store_true",
                        help="include transitive F/D/M references in both directions, across statuses")
    parser.add_argument("--limit", type=_positive, default=50, help="maximum returned rows (default 50)")
    parser.add_argument("--offset", type=_nonnegative, default=0, help="skip matching rows")
    parser.add_argument("--columns", help="comma-separated projection; id,status always included")
    parser.add_argument("--format", choices=("json", "md"), default="json")
    args = parser.parse_args(argv)
    columns = [name.strip() for name in args.columns.split(",")] if args.columns is not None else None
    try:
        result = query_ledger(args.ledger, ids=args.ids, statuses=args.statuses, query=args.query,
                              related=args.related, limit=args.limit, offset=args.offset, columns=columns)
    except LedgerError as exc:
        print(json.dumps({"error": {"code": "invalid_ledger_or_query", "message": str(exc)},
                          "source": {"path": str(args.ledger.resolve())}}, ensure_ascii=False),
              file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.format == "json"
          else render_markdown(result))
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
