
import csv
from collections import Counter
from pathlib import Path

import pymupdf


PROJECT_ROOT = Path(__file__).resolve().parents[1]

TOC_PDF = (
    PROJECT_ROOT
    / "data"
    / "table_of_contents"
    / "Key for keys + artists.pdf"
)

OUTPUT_CSV = (
    PROJECT_ROOT
    / "data"
    / "metadata"
    / "songs.csv"
)

# Keys currently represented in the original TOC.
KEYS = {"G", "D", "C", "A"}


def import_toc():
    counts = Counter()
    songs = []
    current_key = None

    with pymupdf.open(TOC_PDF) as document:
        for page in document:
            for line in page.get_text().splitlines():
                entry = line.strip()

                if not entry:
                    continue

                # Introductory explanation in the PDF.
                if entry.startswith("Bolded artist"):
                    continue

                # Beginning of a new key section.
                if entry in KEYS:
                    current_key = entry
                    continue

                if current_key is None:
                    raise ValueError(
                        f"Entry found before a key: {entry}"
                    )

                counts[current_key] += 1
                position = counts[current_key]

                songs.append({
                    "id": f"{current_key}{position:03d}",
                    "key": current_key,
                    "position": position,
                    "toc_entry": entry,
                    "source_pdf": "",
                })

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_CSV.open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "id",
                "key",
                "position",
                "toc_entry",
                "source_pdf",
            ],
        )
        writer.writeheader()
        writer.writerows(songs)

    print(f"Created: {OUTPUT_CSV}")
    print(f"Total songs: {len(songs)}")

    for key, count in counts.items():
        print(f"  {key}: {count} songs")


if __name__ == "__main__":
    import_toc()

