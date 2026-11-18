"""Apply only unambiguous, explicit key suggestions from the key-audit report.

Usage:
    python scripts/audit_keys.py
    python scripts/apply_key_suggestions.py --check
    python scripts/apply_key_suggestions.py --apply

Never alters source PDFs, song_uid, legacy id, position or status. A timestamped
catalogue backup is written under output/backups/ before any change.
"""
import argparse
import csv
import os
import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "data" / "metadata" / "songs.csv"
AUDIT = ROOT / "output" / "key_audit.csv"
BACKUPS = ROOT / "output" / "backups"

VALID_KEY = re.compile(r"[A-G](?:#|b)?(?:m|min)?\Z")
UNKNOWN = {"", "u", "unknown", "unsorted", "none", "?"}


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        return fields, list(reader)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Preview; do not modify files")
    mode.add_argument("--apply", action="store_true", help="Back up then apply suggestions")
    args = parser.parse_args()

    fields, songs = read_csv(CATALOGUE)
    audit_fields, reports = read_csv(AUDIT)
    required = {"song_uid", "id", "key", "key_source", "source_pdf", "title", "status"}
    audit_required = {"id", "current_key", "source_pdf", "filename_clue", "chart_explicit_clue", "suggested_key", "finding"}
    if not required.issubset(fields) or not audit_required.issubset(audit_fields):
        raise SystemExit("Unexpected catalogue or key-audit columns; no files changed.")

    uids = [r["song_uid"].strip() for r in songs]
    legacy_ids = [r["id"].strip() for r in songs]
    if not all(uids) or len(set(uids)) != len(uids) or len(set(legacy_ids)) != len(legacy_ids):
        raise SystemExit("Blank or duplicated song identifiers; no files changed.")
    by_id = {r["id"].strip(): r for r in songs}
    suggestions = [r for r in reports if r["finding"].strip() == "SUGGEST_KEY"]
    counts = Counter(r["finding"].strip() for r in reports)
    errors = []
    edits = []
    seen = set()
    for suggestion in suggestions:
        ident = suggestion["id"].strip()
        target = suggestion["suggested_key"].strip()
        if ident in seen:
            errors.append(f"Duplicate audit suggestion: {ident}")
            continue
        seen.add(ident)
        song = by_id.get(ident)
        if song is None:
            errors.append(f"{ident}: catalogue entry missing")
            continue
        if song["key"].strip().casefold() not in UNKNOWN:
            errors.append(f"{ident}: catalogue key is no longer Unknown")
            continue
        if suggestion["current_key"].strip().casefold() not in UNKNOWN:
            errors.append(f"{ident}: audit did not record an Unknown key")
            continue
        if suggestion["source_pdf"].strip() != song["source_pdf"].strip():
            errors.append(f"{ident}: source PDF changed since audit")
            continue
        if not VALID_KEY.fullmatch(target):
            errors.append(f"{ident}: invalid proposed key {target!r}")
            continue
        filename_clues = [x.strip() for x in suggestion["filename_clue"].split(";") if x.strip()]
        chart_clues = [x.strip() for x in suggestion["chart_explicit_clue"].split(";") if x.strip()]
        if set(filename_clues + chart_clues) != {target}:
            errors.append(f"{ident}: missing or ambiguous explicit evidence for {target}")
            continue
        provenance = "filename" if filename_clues else "chart"
        edits.append((song, target, provenance))

    print("KEY SUGGESTION REVIEW")
    print("=" * 22)
    print(f"Catalogue entries: {len(songs)}")
    print(f"Audit suggestions: {len(suggestions)}")
    print(f"Unresolved conflicts in audit: {counts['KEY_CONFLICT'] + counts['CONFLICTING_CLUES']}")
    print("\nProposed changes:")
    for song, key, provenance in edits:
        print(f"  {song['song_uid']} ({song['id']}): {song['title']} | Unknown -> {key} [{provenance}]")
    if errors:
        print("\nERRORS (no changes made):")
        for error in errors:
            print("  " + error)
        raise SystemExit(1)

    print("\nPreserved: song_uid, legacy id, position, title, source_pdf, status, and source PDFs.")
    if args.check:
        print("Preview only; no files changed.")
        return
    if not edits:
        print("Nothing to apply.")
        return

    BACKUPS.mkdir(parents=True, exist_ok=True)
    backup = BACKUPS / f"songs_before_key_corrections_{datetime.now():%Y%m%d_%H%M%S_%f}.csv"
    shutil.copy2(CATALOGUE, backup)
    for song, key, provenance in edits:
        song["key"] = key
        song["key_source"] = provenance
    temp = CATALOGUE.with_suffix(".csv.tmp")
    try:
        with temp.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(songs)
        os.replace(temp, CATALOGUE)
    finally:
        if temp.exists():
            temp.unlink()
    print(f"Applied {len(edits)} key corrections.")
    print(f"Backup: {backup}")
    print(f"Catalogue: {CATALOGUE}")
    print("Source PDFs unchanged. Conflicts not applied.")


if __name__ == "__main__":
    main()
