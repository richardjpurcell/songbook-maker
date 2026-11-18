"""Safely consolidate explicitly approved duplicate song records.

Usage:
    python scripts/consolidate_reviewed.py --check
    python scripts/consolidate_reviewed.py --apply

The input file is data/metadata/duplicate_review_approved.csv, copied from the
supplied review CSV. Only rows with decision=approve are applied. All changes
are validated before any write. No source PDFs are modified.
"""
import argparse
import csv
import json
import os
import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / 'data/metadata/songs.csv'
REVIEW = ROOT / 'data/metadata/duplicate_review_approved.csv'
PDF_DIR = ROOT / 'data/song_sheets'
BACKUP_DIR = ROOT / 'output/backups'
REPORT_DIR = ROOT / 'output'
ADDED_COLUMNS = ['capo_fret', 'chord_shapes_key']
REQUIRED_REVIEW = {'song_uid', 'matched_pdf', 'current_pdf_owner', 'decision',
                   'verified_sounding_key', 'chord_shapes_key', 'capo_fret'}
REQUIRED_CATALOGUE = {'song_uid', 'id', 'key', 'position', 'title', 'status',
                      'source_pdf', 'key_source'}
KEY_RE = re.compile(r'[A-G](?:#|b)?m?\Z')


def read_csv(path):
    with path.open(newline='', encoding='utf-8-sig') as fh:
        reader = csv.DictReader(fh)
        return list(reader), list(reader.fieldnames or [])


def write_csv_atomic(path, rows, columns):
    temp = path.with_name(path.name + '.tmp')
    try:
        with temp.open('w', newline='', encoding='utf-8') as fh:
            writer = csv.DictWriter(fh, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def valid_key(value):
    return bool(KEY_RE.fullmatch(value))


def prepare(catalogue, review):
    errors, actions = [], []
    uids = [r.get('song_uid', '').strip() for r in catalogue]
    if len(set(uids)) != len(uids) or not all(uids):
        return [], ['Duplicate or blank catalogue song_uid values']
    by_uid = {r['song_uid'].strip(): r for r in catalogue}
    selected = [r for r in review if r.get('decision', '').strip().lower() == 'approve']
    bad_decisions = [r.get('song_uid', '?') for r in review
                     if r.get('decision', '').strip().lower() not in ('', 'approve', 'skip', 'hold')]
    if bad_decisions:
        errors.append('Unknown review decision for: ' + ', '.join(bad_decisions))
    targets = [r.get('song_uid', '').strip() for r in selected]
    if any(count > 1 for count in Counter(targets).values()):
        errors.append('Review contains duplicate approved target IDs')
    owners = []
    for r in selected:
        uid = r['song_uid'].strip()
        filename = r['matched_pdf'].strip()
        owner_ref = r['current_pdf_owner'].strip()
        match = re.fullmatch(r'(S\d{5,})\s*\(([^()]*)\)', owner_ref)
        if not match:
            errors.append(f'{uid}: invalid owner reference: {owner_ref!r}')
            continue
        owner_uid, owner_legacy_id = match.groups()
        if uid not in by_uid or owner_uid not in by_uid:
            errors.append(f'{uid}: missing target or owner')
            continue
        if uid == owner_uid:
            errors.append(f'{uid}: target and owner are identical')
            continue
        target = by_uid[uid]
        owner = by_uid[owner_uid]
        if owner['id'].strip() != owner_legacy_id:
            errors.append(f'{uid}: owner legacy ID changed since review')
        if target['source_pdf'].strip():
            errors.append(f'{uid}: target already has a PDF; review before replacing')
        if target['status'].strip().lower() not in ('review', 'placeholder'):
            errors.append(f'{uid}: target status is not review or placeholder')
        if owner['source_pdf'].strip() != filename:
            errors.append(f'{uid}: owner PDF changed since review')
        if owner['status'].strip().lower() == 'exclude':
            errors.append(f'{uid}: owner already excluded')
        if not filename or Path(filename).name != filename or not (PDF_DIR / filename).is_file():
            errors.append(f'{uid}: unavailable or unsafe PDF filename: {filename!r}')
        sounding = r['verified_sounding_key'].strip()
        shapes = r['chord_shapes_key'].strip()
        capo = r['capo_fret'].strip()
        if not valid_key(sounding):
            errors.append(f'{uid}: approved record requires a valid verified sounding key')
        if shapes and not valid_key(shapes):
            errors.append(f'{uid}: invalid chord-shape key {shapes!r}')
        if capo and (not capo.isdigit() or not 0 <= int(capo) <= 12):
            errors.append(f'{uid}: invalid capo fret {capo!r}')
        if bool(capo) != bool(shapes):
            errors.append(f'{uid}: capo and chord-shape key must be supplied together')
        if 'legacy_id' in r and r['legacy_id'].strip() != target['id'].strip():
            errors.append(f'{uid}: target legacy ID changed since review')
        owners.append(owner_uid)
        actions.append({'target': uid, 'owner': owner_uid, 'filename': filename,
                        'key': sounding, 'shapes': shapes, 'capo': capo,
                        'old_key': target['key'], 'old_status': target['status'],
                        'owner_old_status': owner['status'], 'title': target['title']})
    if len(owners) != len(set(owners)):
        errors.append('An imported owner is selected for more than one target')
    if set(owners) & set(targets):
        errors.append('An approved owner is also an approved target')
    return actions, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    catalogue, columns = read_csv(CATALOGUE)
    review, review_columns = read_csv(REVIEW)
    missing = REQUIRED_CATALOGUE - set(columns)
    missing_review = REQUIRED_REVIEW - set(review_columns)
    if missing or missing_review:
        raise SystemExit(f'Missing columns: catalogue={sorted(missing)}, review={sorted(missing_review)}')
    actions, errors = prepare(catalogue, review)
    print('REVIEWED SONG CONSOLIDATION')
    print('=' * 27)
    print(f'Catalogue records: {len(catalogue)}')
    print(f'Approved decisions: {len(actions)}')
    for a in actions:
        extra = f"; {a['shapes']} shapes, capo {a['capo']}" if a['capo'] else ''
        print(f"  {a['target']} <= {a['owner']}: {a['title']} | "
              f"{a['old_key']} -> {a['key']}{extra}")
    if errors:
        print('\nERRORS — no changes made:')
        for error in errors:
            print('  ' + error)
        raise SystemExit(1)
    if args.check:
        print('\nPreview only. No files changed.')
        return
    if not actions:
        print('\nNo approved records. No files changed.')
        return

    by_uid = {r['song_uid'].strip(): r for r in catalogue}
    for a in actions:
        target, owner = by_uid[a['target']], by_uid[a['owner']]
        target.update({'source_pdf': a['filename'], 'status': 'include',
                       'key': a['key'], 'key_source': 'chart_reviewed',
                       'chord_shapes_key': a['shapes'], 'capo_fret': a['capo']})
        # Preserve owner record for historical traceability, but omit from build.
        owner['status'] = 'exclude'
    for column in ADDED_COLUMNS:
        if column not in columns:
            columns.append(column)
    for row in catalogue:
        for column in ADDED_COLUMNS:
            row.setdefault(column, '')

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = BACKUP_DIR / f'songs_before_consolidation_{stamp}.csv'
    shutil.copy2(CATALOGUE, backup)
    log = REPORT_DIR / f'consolidation_{stamp}.json'
    # Durable record of old and new state, including original keys and owners.
    log.write_text(json.dumps({'backup': str(backup), 'actions': actions}, indent=2,
                              ensure_ascii=False) + '\n', encoding='utf-8')
    write_csv_atomic(CATALOGUE, catalogue, columns)
    print(f'\nConsolidated: {len(actions)} original TOC records')
    print(f'Excluded imported duplicates: {len(actions)}')
    print(f'Backup: {backup}')
    print(f'Audit log: {log}')
    print(f'Catalogue: {CATALOGUE}')
    print('Source PDFs not modified.')


if __name__ == '__main__':
    main()
