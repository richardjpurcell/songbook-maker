"""One-time, non-destructive migration to the revised songbook catalogue.

Run from any working directory: python scripts/reconcile_catalogue.py
Creates a backup, updates songs.csv, and creates a source-PDF inventory.
Never edits source PDFs or discards unapproved matching suggestions.
"""
import csv
import shutil
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METADATA = ROOT / 'data' / 'metadata'
SONGS = METADATA / 'songs.csv'
REVIEW = METADATA / 'match_review.csv'
PDF_DIR = ROOT / 'data' / 'song_sheets'
INVENTORY = METADATA / 'pdf_inventory.csv'
BACKUP = ROOT / 'output' / 'songs_before_migration.csv'


def read_rows(path):
    with path.open(newline='', encoding='utf-8-sig') as handle:
        reader = csv.DictReader(handle)
        return list(reader), set(reader.fieldnames or [])


def write_rows(path, rows, fields):
    # Write via temporary file to avoid leaving a half-written CSV.
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def main():
    songs, song_fields = read_rows(SONGS)
    reviews, review_fields = read_rows(REVIEW)
    required_songs = {'id', 'key', 'position', 'toc_entry', 'source_pdf'}
    required_reviews = {'id', 'approved_pdf', 'review_status'}
    if not required_songs <= song_fields or not required_reviews <= review_fields:
        raise SystemExit('CSV columns do not match the expected old format. No changes made.')
    if 'status' in song_fields or INVENTORY.exists() or BACKUP.exists():
        raise SystemExit('Migration appears to have run already. No changes made.')
    if len(songs) != len({s['id'] for s in songs}):
        raise SystemExit('Duplicate song IDs. No changes made.')
    if len(reviews) != len({r['id'] for r in reviews}):
        raise SystemExit('Duplicate review IDs. No changes made.')
    review_by_id = {r['id']: r for r in reviews}
    if set(review_by_id) != {s['id'] for s in songs}:
        raise SystemExit('Song and review IDs do not match. No changes made.')

    pdfs = sorted((p.name for p in PDF_DIR.iterdir() if p.is_file() and p.suffix.lower() == '.pdf'), key=str.casefold)
    available = set(pdfs)
    assigned = []
    migrated = []
    approved_count = 0
    for song in songs:
        review = review_by_id[song['id']]
        decision = review['review_status'].strip().lower()
        if decision not in {'approved', 'review', 'missing', ''}:
            raise SystemExit(f"Unexpected status for {song['id']}: {decision}. No changes made.")
        original_pdf = song['source_pdf'].strip()
        if original_pdf:
            raise SystemExit(f"{song['id']} already has a source_pdf. No changes made; inspect it first.")
        filename = review['approved_pdf'].strip() if decision == 'approved' else ''
        if decision == 'approved':
            if filename not in available:
                raise SystemExit(f"Approved PDF for {song['id']} not found: {filename!r}. No changes made.")
            if Path(filename).name != filename:
                raise SystemExit(f"Invalid filename for {song['id']}. No changes made.")
            assigned.append(filename)
            approved_count += 1
        migrated.append({
            'id': song['id'],
            'key': song['key'],
            'position': song['position'],
            'toc_entry': song['toc_entry'],
            'title': song['toc_entry'],
            'artist': '',
            'status': 'include' if decision == 'approved' else ('placeholder' if decision == 'missing' else 'review'),
            'source_pdf': filename,
        })

    # Preserve user data first, then write the new catalogue.
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SONGS, BACKUP)
    write_rows(SONGS, migrated, ['id', 'key', 'position', 'toc_entry', 'title', 'artist', 'status', 'source_pdf'])

    assigned_set = set(assigned)
    unassigned_pdfs = [name for name in pdfs if name not in assigned_set]
    inventory_rows = [
        {'filename': name, 'action': 'review', 'title': '', 'key': '', 'artist': ''}
        for name in unassigned_pdfs
    ]
    write_rows(INVENTORY, inventory_rows, ['filename', 'action', 'title', 'key', 'artist'])

    print(f'Original catalogue records preserved: {len(songs)}')
    print(f'Approved charts migrated as include: {approved_count}')
    print(f'Other catalogue entries retained: {len(songs) - approved_count}')
    print(f'PDFs available: {len(pdfs)}')
    print(f'PDFs not yet assigned: {len(unassigned_pdfs)}')
    print(f'Updated catalogue: {SONGS}')
    print(f'New PDF inventory: {INVENTORY}')
    print(f'Backup of previous catalogue: {BACKUP}')
    if any(v > 1 for v in Counter(assigned).values()):
        print('NOTE: Some approved source PDFs are used more than once; review later.')
    print('No song-sheet PDFs were modified.')


if __name__ == '__main__':
    main()
