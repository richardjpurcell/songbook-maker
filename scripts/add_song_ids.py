"""One-time, conservative addition of stable song identities and key provenance.

Usage: python scripts/add_song_ids.py --check
       python scripts/add_song_ids.py --apply
"""
import argparse
import csv
import os
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / 'data' / 'metadata' / 'songs.csv'
BACKUPS = ROOT / 'output' / 'backups'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true', help='Preview without changes')
    mode.add_argument('--apply', action='store_true', help='Back up and update the catalogue')
    args = parser.parse_args()

    with CATALOGUE.open(newline='', encoding='utf-8-sig') as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    required = {'id', 'key', 'position', 'title', 'status', 'source_pdf'}
    if not required.issubset(fields):
        raise SystemExit('Catalogue does not have the expected columns; no changes made.')
    if not rows:
        raise SystemExit('Catalogue is empty; no changes made.')

    if 'song_uid' in fields or 'key_source' in fields:
        raise SystemExit('Catalogue already has a migration column. No changes made; inspect it before proceeding.')

    ids = [row['id'].strip() for row in rows]
    duplicate_ids = [value for value, count in Counter(ids).items() if count > 1]
    if duplicate_ids or any(not value for value in ids):
        raise SystemExit(f'Blank or duplicate legacy IDs found: {duplicate_ids[:10]}; no changes made.')

    proposed = []
    for index, row in enumerate(rows, start=1):
        new_row = dict(row)
        new_row['song_uid'] = f'S{index:05d}'
        key = row['key'].strip()
        if key.lower() in ('', 'u', 'unknown', 'unsorted'):
            new_row['key_source'] = 'unknown'
        elif index <= 174:
            new_row['key_source'] = 'original_toc'
        else:
            new_row['key_source'] = 'imported_unverified'
        proposed.append(new_row)

    sources = Counter(row['key_source'] for row in proposed)
    print(f'Catalogue entries: {len(rows)}')
    print(f'Permanent IDs to create: {len(rows)}')
    print('Key provenance:')
    for name, count in sorted(sources.items()):
        print(f'  {name}: {count}')
    print('Existing keys, titles, statuses, files, and legacy IDs: unchanged')

    if args.check:
        print('\nPreview only; no files changed.')
        return

    BACKUPS.mkdir(parents=True, exist_ok=True)
    backup = BACKUPS / f'songs_before_uid_{datetime.now().strftime("%Y%m%d_%H%M%S_%f")}.csv'
    shutil.copy2(CATALOGUE, backup)
    temp = CATALOGUE.with_suffix('.csv.tmp')
    new_fields = ['song_uid'] + fields + ['key_source']
    try:
        with temp.open('w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=new_fields)
            writer.writeheader()
            writer.writerows(proposed)
        os.replace(temp, CATALOGUE)
    finally:
        if temp.exists():
            temp.unlink()
    print(f'\nUpdated: {CATALOGUE}')
    print(f'Backup: {backup}')

if __name__ == '__main__':
    main()
