
import csv
from collections import Counter
from pathlib import Path

import pymupdf


ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "data/metadata/songs.csv"
PDF_DIR = ROOT / "data/song_sheets"
REPORT = ROOT / "output/build_report.txt"

REQUIRED_COLUMNS = {
    "id", "key", "position", "toc_entry", "source_pdf"
}


def main():
    with CATALOGUE.open(
        newline="", encoding="utf-8-sig"
    ) as file:
        reader = csv.DictReader(file)

        if not REQUIRED_COLUMNS.issubset(reader.fieldnames or []):
            raise ValueError("Catalogue is missing required columns")

        songs = list(reader)

    available = {
        path.name: path
        for path in PDF_DIR.glob("*.pdf")
    }

    assigned = []
    unassigned = []
    missing = []
    invalid = []
    errors = []

    ids = Counter(song["id"].strip() for song in songs)

    for song in songs:
        song_id = song["id"].strip()
        filename = song["source_pdf"].strip()

        if not filename:
            unassigned.append(
                f"{song_id}: {song['toc_entry']}"
            )
            continue

        # Only filenames inside song_sheets are allowed.
        if Path(filename).name != filename:
            errors.append(
                f"{song_id}: Invalid source path: {filename}"
            )
            continue

        assigned.append(filename)

        if filename not in available:
            missing.append(f"{song_id}: {filename}")
            continue

        try:
            with pymupdf.open(available[filename]) as doc:
                if len(doc) == 0:
                    invalid.append(f"{song_id}: {filename}")
        except Exception as exc:
            invalid.append(
                f"{song_id}: {filename} ({exc})"
            )

    duplicate_ids = [
        song_id for song_id, count in ids.items()
        if count > 1
    ]

    assigned_counts = Counter(assigned)
    duplicate_files = [
        filename for filename, count in assigned_counts.items()
        if count > 1
    ]

    unlisted = sorted(set(available) - set(assigned))

    ready = (
        len(songs)
        - len(unassigned)
        - len(missing)
        - len(invalid)
        - len(errors)
    )

    report = [
        "SONGBOOK CATALOGUE VALIDATION REPORT",
        "=" * 38,
        "",
        f"Catalogue entries:        {len(songs)}",
        f"Available source PDFs:    {len(available)}",
        f"Ready entries:            {ready}",
        f"Unassigned entries:       {len(unassigned)}",
        f"Missing assigned PDFs:    {len(missing)}",
        f"Unreadable/empty PDFs:    {len(invalid)}",
        f"Unlisted PDFs:            {len(unlisted)}",
        f"Duplicate IDs:            {len(duplicate_ids)}",
        f"Repeated PDF assignments: {len(duplicate_files)}",
        "",
    ]

    def add_section(title, items):
        report.append(title)
        report.append("-" * len(title))
        report.extend(items or ["None"])
        report.append("")

    add_section("UNASSIGNED SONGS", unassigned)
    add_section("MISSING ASSIGNED PDFs", missing)
    add_section("UNREADABLE OR EMPTY PDFs", invalid)
    add_section("INVALID SOURCE PATHS", errors)
    add_section("DUPLICATE SONG IDs", duplicate_ids)
    add_section("REPEATED PDF ASSIGNMENTS", duplicate_files)
    add_section("UNLISTED PDFs", unlisted)

    report.extend([
        "NOTE",
        "----",
        "This report validates the catalogue.",
        "No master PDF was generated.",
        "Unlisted PDFs are informational, not errors.",
    ])

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        "\n".join(report) + "\n",
        encoding="utf-8"
    )

    print("\n".join(report[:13]))
    print(f"\nFull report: {REPORT}")


if __name__ == "__main__":
    main()

