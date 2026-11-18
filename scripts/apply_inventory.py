
import argparse
import csv
import os
import re
import shutil
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "data/metadata/songs.csv"
INVENTORY = ROOT / "data/metadata/pdf_inventory.csv"
PDF_DIR = ROOT / "data/song_sheets"
BACKUP_DIR = ROOT / "output"


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path, rows, columns):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    songs, song_columns = read_csv(CATALOGUE)
    inventory, inventory_columns = read_csv(INVENTORY)

    required_song_columns = {
        "id", "key", "position", "toc_entry",
        "title", "artist", "status", "source_pdf"
    }
    required_inventory_columns = {
        "filename", "action", "title", "key", "artist"
    }

    if not required_song_columns.issubset(song_columns):
        raise ValueError("Unexpected songs.csv columns")

    if not required_inventory_columns.issubset(inventory_columns):
        raise ValueError("Unexpected pdf_inventory.csv columns")

    used_files = {
        row["source_pdf"].strip()
        for row in songs
        if row["source_pdf"].strip()
    }

    used_ids = {row["id"].strip() for row in songs}
    positions = Counter()

    for song in songs:
        key = song["key"].strip()
        positions[key] = max(
            positions[key], int(song["position"])
        )

    additions = []
    errors = []
    pending_files = set()

    for row in inventory:
        if row["action"].strip().lower() != "add":
            continue

        filename = row["filename"].strip()
        title = row["title"].strip()
        key = row["key"].strip()
        artist = row["artist"].strip()

        if not title or not key:
            errors.append(
                f"{filename}: title and key are required"
            )
            continue

        if not re.fullmatch(r"[A-G](?:#|b)?m?", key):
            errors.append(f"{filename}: invalid key '{key}'")
            continue

        if Path(filename).name != filename or not filename:
            errors.append(f"{filename}: invalid filename")
            continue

        if not (PDF_DIR / filename).is_file():
            errors.append(f"{filename}: PDF not found")
            continue

        if filename in used_files or filename in pending_files:
            errors.append(
                f"{filename}: already assigned or selected twice"
            )
            continue

        pending_files.add(filename)
        positions[key] += 1

        song_id = f"{key}{positions[key]:03d}"

        if song_id in used_ids:
            errors.append(f"{filename}: duplicate ID {song_id}")
            continue

        used_ids.add(song_id)

        additions.append((row, {
            "id": song_id,
            "key": key,
            "position": str(positions[key]),
            "toc_entry": title,
            "title": title,
            "artist": artist,
            "status": "include",
            "source_pdf": filename,
        }))

    print(f"Existing catalogue entries: {len(songs)}")
    print(f"Proposed additions: {len(additions)}")

    for _, song in additions:
        print(
            f"  {song['id']}: {song['title']} "
            f"[{song['source_pdf']}]"
        )

    if errors:
        print("\nERRORS:")
        for error in errors:
            print(f"  {error}")
        raise SystemExit("No changes made. Correct the errors first.")

    if args.check:
        print("\nPreview only. No files changed.")
        return

    if not additions:
        print("\nNothing to add.")
        return

    BACKUP_DIR.mkdir(exist_ok=True)

    shutil.copy2(
        CATALOGUE,
        BACKUP_DIR / "songs_before_inventory.csv"
    )
    shutil.copy2(
        INVENTORY,
        BACKUP_DIR / "inventory_before_apply.csv"
    )

    for row, song in additions:
        songs.append(song)
        row["action"] = "added"

    write_csv(CATALOGUE, songs, song_columns)
    write_csv(INVENTORY, inventory, inventory_columns)

    print(f"\nAdded {len(additions)} songs.")
    print("Inventory rows marked 'added'.")
    print("Backups saved in output/.")


if __name__ == "__main__":
    main()

