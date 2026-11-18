
import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "data/metadata/match_review.csv"

AUTO_SUGGEST_THRESHOLD = 0.95


def main():
    with REVIEW.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    if not rows:
        raise ValueError("Review file is empty")

    for column in ("approved_pdf", "review_status"):
        if column not in fieldnames:
            fieldnames.append(column)

    suggested = 0
    needs_review = 0

    for row in rows:
        # Preserve any existing human decisions.
        if row.get("review_status", "").strip():
            continue

        score = float(row.get("score_1") or 0)
        second_score = float(row.get("score_2") or 0)

        if score >= AUTO_SUGGEST_THRESHOLD and (
            score - second_score >= 0.15
        ):
            # This is a suggestion, not an approval.
            row["approved_pdf"] = row["candidate_1"]
            row["review_status"] = "review"
            suggested += 1
        else:
            row["approved_pdf"] = ""
            row["review_status"] = "review"
            needs_review += 1

    with REVIEW.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Review entries: {len(rows)}")
    print(f"Suggested filenames: {suggested}")
    print(f"No suggested filename: {needs_review}")
    print(f"Updated: {REVIEW}")


if __name__ == "__main__":
    main()

