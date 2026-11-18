"""Synchronize local PDFs into songs.csv without modifying source PDFs.

Usage:
    python scripts/sync_catalogue.py          # preview
    python scripts/sync_catalogue.py --apply  # create backup and apply

New unambiguous PDFs are added to the catalogue with permanent song_uid values. Uncertain filename matches
are marked 'review' and reported rather than silently selected. An unknown
key is represented as 'Unknown' (section ID prefix U).
"""
import argparse
import csv
import re
import shutil
import unicodedata
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SONGS = ROOT / "data/metadata/songs.csv"
PDF_DIR = ROOT / "data/song_sheets"
REPORT = ROOT / "output/sync_report.txt"
BACKUP_DIR = ROOT / "output/backups"

REQUIRED = {"song_uid", "id", "key", "position", "toc_entry", "title", "artist", "status", "source_pdf", "key_source"}
KNOWN_KEYS = {n + suffix for n in "ABCDEFG" for suffix in ("", "#", "b", "m", "#m", "bm")}


def clean(text):
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("’", "'")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def song_title(text):
    # Drop a trailing artist credit; do not discard parentheses within titles.
    return clean(re.sub(r"\s*\([^()]*\)\s*$", "", text).strip(" ."))


def derive(filename):
    stem = Path(filename).stem.strip()
    # Infer a key ONLY from explicit trailing key notation.
    key = "Unknown"
    match = re.search(r"(?:\s+in\s+|\s+-\s*|\s+\()([A-Ga-g](?:#|b)?m?)\)?\s*$", stem)
    if match:
        proposed = match.group(1).upper()[0] + match.group(1)[1:]
        if proposed in KNOWN_KEYS:
            key = proposed
            stem = stem[:match.start()].strip(" -")
    # Common trailing version numbers: "-2", " 3".
    stem = re.sub(r"(?:[- ]+\d+)\s*$", "", stem)
    title = " ".join(stem.replace("_", " ").split())
    return title or Path(filename).stem, key


def read_catalogue():
    with SONGS.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        if not REQUIRED <= set(fields):
            raise SystemExit("songs.csv has unexpected columns; no changes made.")
        rows = list(reader)
    ids = [r["id"].strip() for r in rows]
    if len(ids) != len(set(ids)):
        raise SystemExit("Duplicate catalogue IDs; no changes made.")
    uids = [r["song_uid"].strip() for r in rows]
    if any(not re.fullmatch(r"S\d{5,}", uid) for uid in uids) or len(uids) != len(set(uids)):
        raise SystemExit("Missing, invalid, or duplicate permanent song IDs; no changes made.")
    return rows, fields


def write_catalogue(rows, fields):
    tmp = SONGS.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(SONGS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write proposed catalogue changes")
    args = parser.parse_args()
    songs, fields = read_catalogue()
    files = sorted((p.name for p in PDF_DIR.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"), key=str.casefold)
    assigned = {r["source_pdf"].strip() for r in songs if r["source_pdf"].strip()}
    positions = Counter()
    used_ids = {r["id"].strip() for r in songs}
    next_uid = max((int(r["song_uid"][1:]) for r in songs), default=0) + 1
    for row in songs:
        try:
            positions[row["key"].strip()] = max(positions[row["key"].strip()], int(row["position"]))
        except ValueError:
            raise SystemExit(f"Invalid position in {row['id']}; no changes made.")

    existing = list(songs)
    attached, created, uncertain = [], [], []
    for filename in files:
        if filename in assigned:
            continue
        name, inferred_key = derive(filename)
        normalized = clean(name)
        # Exact matching is safe only for one currently unassigned entry.
        exact = [r for r in existing if not r["source_pdf"].strip() and song_title(r["title"] or r["toc_entry"]) == normalized]
        if len(exact) == 1 and (inferred_key == "Unknown" or inferred_key == exact[0]["key"].strip()):
            record = exact[0]
            record["source_pdf"] = filename
            # Keep 'review' as review: a filename association isn't a human approval.
            attached.append((record["id"], filename))
            assigned.add(filename)
            continue

        # Detect possible duplicates/alternate versions; do not silently include.
        scored = sorted(((SequenceMatcher(None, normalized, song_title(r["title"] or r["toc_entry"])).ratio(), r["id"]) for r in existing), reverse=True)
        likely = [(score, identifier) for score, identifier in scored[:3] if score >= 0.66]
        ambiguous = bool(likely) or len(exact) > 1
        key = inferred_key
        positions[key] += 1
        prefix = "U" if key == "Unknown" else key
        candidate_id = f"{prefix}{positions[key]:03d}"
        while candidate_id in used_ids:
            positions[key] += 1
            candidate_id = f"{prefix}{positions[key]:03d}"
        used_ids.add(candidate_id)
        record = {column: "" for column in fields}
        record.update({"song_uid": f"S{next_uid:05d}", "key_source": "unknown" if key == "Unknown" else "imported_unverified",
                       "id": candidate_id, "key": key, "position": str(positions[key]),
                       "toc_entry": name, "title": name, "artist": "",
                       "status": "review" if ambiguous else "include", "source_pdf": filename})
        next_uid += 1
        songs.append(record)
        created.append(record)
        if ambiguous:
            uncertain.append((candidate_id, filename, ", ".join(f"{ident} ({score:.2f})" for score, ident in likely) or "multiple exact matches"))
        assigned.add(filename)

    lines = ["SONGBOOK SYNCHRONIZATION REPORT", "=" * 32,
             f"Source PDFs: {len(files)}", f"Existing catalogue songs: {len(existing)}",
             f"Attached to existing entries (left for review): {len(attached)}",
             f"New catalogue entries: {len(created)}",
             f"New entries needing review (possible duplicates): {len(uncertain)}",
             f"New entries in Unknown key: {sum(r['key'] == 'Unknown' for r in created)}", ""]
    lines += ["ATTACHED TO EXISTING", "--------------------"] + [f"{sid}: {name}" for sid, name in attached] + [""]
    lines += ["NEW ENTRIES", "-----------"] + [f"{r['id']} [{r['key']}] {r['title']} ({r['status']}) <- {r['source_pdf']}" for r in created] + [""]
    lines += ["POSSIBLE DUPLICATES / ARRANGEMENTS", "----------------------------------"] + [f"{sid}: {name}; similar to {notes}" for sid, name, notes in uncertain] + [""]

    print("\n".join(lines[:9]))
    if not args.apply:
        print("Preview only. No files changed. Run with --apply to save.")
        return
    if not created and not attached:
        print("Already synchronized; no catalogue changes.")
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"songs_before_sync_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.csv"
    shutil.copy2(SONGS, backup)
    write_catalogue(songs, fields)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Catalogue updated: {SONGS}")
    print(f"Backup: {backup}")
    print(f"Detailed report: {REPORT}")
    print("No PDFs modified. Existing approved selections preserved.")


if __name__ == "__main__":
    main()
