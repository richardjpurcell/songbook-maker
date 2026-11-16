
import csv
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CATALOGUE = ROOT / "data/metadata/songs.csv"
PDF_DIRECTORY = ROOT / "data/song_sheets"
REPORT = ROOT / "data/metadata/match_report.csv"


def normalize(text):
    """Normalize text for approximate comparison."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        char for char in text
        if not unicodedata.combining(char)
    )
    text = text.lower()
    text = text.replace("_", " ")
    text = text.replace("’", "'")
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return " ".join(text.split())


def catalogue_title(entry):
    """Remove trailing artist/arrangement information."""
    title = re.sub(r"\s*\([^)]*\)\s*$", "", entry)
    title = re.sub(r"\s*\[[^]]*\]\s*$", "", title)
    return normalize(title)


def filename_title(filename):
    """Remove common filename annotations."""
    title = Path(filename).stem

    title = re.sub(
        r"\s*\([^)]*\)", "", title
    )

    title = re.sub(
        r"\s+in\s+[A-G](?:m|#|b)?\b",
        "", title,
        flags=re.IGNORECASE,
    )

    title = re.sub(r"[- ]+\d+$", "", title)

    return normalize(title)


def similarity(left, right):
    return SequenceMatcher(
        None, left, right
    ).ratio()


def main():
    pdfs = sorted(
        PDF_DIRECTORY.glob("*.pdf"),
        key=lambda path: path.name.lower()
    )

    with CATALOGUE.open(
        newline="", encoding="utf-8"
    ) as file:
        songs = list(csv.DictReader(file))

    results = []

    for song in songs:
        title = catalogue_title(song["toc_entry"])

        candidates = []

        for pdf in pdfs:
            candidate_title = filename_title(pdf.name)
            score = similarity(title, candidate_title)

            candidates.append((score, pdf.name))

        candidates.sort(
            key=lambda item: (-item[0], item[1])
        )

        best = candidates[:3]

        results.append({
            "id": song["id"],
            "key": song["key"],
            "toc_entry": song["toc_entry"],
            "candidate_1": best[0][1] if len(best) > 0 else "",
            "score_1": round(best[0][0], 3) if len(best) > 0 else "",
            "candidate_2": best[1][1] if len(best) > 1 else "",
            "score_2": round(best[1][0], 3) if len(best) > 1 else "",
            "candidate_3": best[2][1] if len(best) > 2 else "",
            "score_3": round(best[2][0], 3) if len(best) > 2 else "",
        })

    with REPORT.open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(results[0].keys())
        )
        writer.writeheader()
        writer.writerows(results)

    strong = sum(
        float(row["score_1"]) >= 0.90
        for row in results
    )

    print(f"Catalogue entries: {len(songs)}")
    print(f"Source PDFs: {len(pdfs)}")
    print(f"Strong candidate matches (>= 0.90): {strong}")
    print(f"Entries requiring closer review: {len(songs) - strong}")
    print(f"Report written to: {REPORT}")


if __name__ == "__main__":
    main()

