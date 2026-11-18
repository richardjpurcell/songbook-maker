#!/usr/bin/env python3
"""Step 73: guarded exclusion of the duplicate Stand My Ground entry.

  python scripts/exclude_step73_duplicate.py --check
  python scripts/exclude_step73_duplicate.py --apply

Only status include -> exclude on S00289; no source PDFs are modified.
"""
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / 'data/metadata/songs.csv'
SHEETS = ROOT / 'data/song_sheets'
OUTPUT = ROOT / 'output'
UID = 'S00289'
TITLE = 'Stand My Ground'
FILENAME = 'Stand My Ground.pdf'
KEEP_UID = "S00024"
KEEP_TITLE = "I Won’t Back Down (Tom Petty)"
KEEP_FILENAME = "I Won_t Back Down.pdf"


def prepare():
    original = CATALOGUE.read_bytes()
    with CATALOGUE.open('r', encoding='utf-8-sig', newline='') as file:
        reader = csv.DictReader(file)
        fields = reader.fieldnames or []
        rows = list(reader)
    needed = {'id', 'song_uid', 'title', 'key', 'status', 'source_pdf'}
    if not needed.issubset(fields):
        raise ValueError(f'Missing columns {needed - set(fields)}')
    if len(rows) != 314 or len(set(r['song_uid'] for r in rows)) != 314:
        raise ValueError('Expected 314 records with unique permanent IDs')
    match = [row for row in rows if row['song_uid'] == UID]
    if len(match) != 1:
        raise ValueError('Expected exactly one record S00289')
    row = match[0]
    expected = {'title': TITLE, 'source_pdf': FILENAME, 'status': 'include', 'key': 'G'}
    for field, value in expected.items():
        if row[field].strip() != value:
            raise ValueError(f'{UID} {field}: expected {value!r}, got {row[field]!r}')
    other = [r for r in rows if r['song_uid'] == KEEP_UID]
    if len(other) != 1:
        raise ValueError(f'Expected exactly one canonical chart {KEEP_UID}')
    canonical = other[0]
    required = {'title': KEEP_TITLE, 'source_pdf': KEEP_FILENAME, 'status': 'include', 'key': 'G'}
    for field, value in required.items():
        if canonical[field].strip() != value:
            raise ValueError(f'{KEEP_UID} {field}: expected {value!r}, got {canonical[field]!r}')
    if canonical is row or canonical['source_pdf'] == FILENAME:
        raise ValueError('Canonical and duplicate must be distinct')
    if sum(r['status'].strip().lower() == 'include' for r in rows) != 210:
        raise ValueError('Expected exactly 210 included arrangements before Step 73')
    for source in [FILENAME, other[0]['source_pdf'].strip()]:
        pdf_path = SHEETS / source
        if not pdf_path.is_file() or pdf_path.name != source:
            raise ValueError(f'Unsafe or missing source PDF: {source!r}')
        with pymupdf.open(pdf_path) as pdf:
            if pdf.page_count < 1:
                raise ValueError(f'Empty source PDF {source!r}')
    return original, fields, rows, row, other[0]


def serialize(fields, rows, original):
    newline = '\r\n' if b'\r\n' in original else '\n'
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator=newline)
    writer.writeheader()
    writer.writerows(rows)
    bom = b'\xef\xbb\xbf' if original.startswith(b'\xef\xbb\xbf') else b''
    new = bom + stream.getvalue().encode('utf-8')
    with io.StringIO(new.decode('utf-8-sig'), newline='') as check:
        assert list(csv.DictReader(check)) == rows
    return new


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--check', action='store_true', help='Preview without changing anything')
    choice.add_argument('--apply', action='store_true', help='Back up and change status only')
    args = parser.parse_args()
    try:
        original, fields, rows, target, canonical = prepare()
    except Exception as exc:
        parser.error(f'Validation failed, nothing changed: {exc}')
    print('STEP 73 — EXCLUDE CONFIRMED DUPLICATE — ' + ('PREVIEW' if args.check else 'APPLY'))
    print(f'Catalogue entries: {len(rows)}; included before: 210; expected after: 209')
    print(f"Exclude: {target['song_uid']} / {target['id']} / {target['title']} / {target['source_pdf']}")
    print(f"Keep:    {canonical['song_uid']} / {canonical['id']} / {canonical['title']} / {canonical['source_pdf']}")
    print('Only the status field changes: include -> exclude. The duplicate PDF stays on disk.')
    if args.check:
        print('PREVIEW ONLY — no files changed.')
        return
    before = {r['song_uid']: dict(r) for r in rows}
    target['status'] = 'exclude'
    diffs = [(r['song_uid'], k) for r in rows for k in fields if r[k] != before[r['song_uid']][k]]
    if diffs != [(UID, 'status')]:
        parser.error(f'Unexpected catalogue changes {diffs!r}; nothing changed')
    updated = serialize(fields, rows, original)
    OUTPUT.mkdir(exist_ok=True)
    backup_dir = OUTPUT / 'backups'
    backup_dir.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = backup_dir / f'songs_before_step73_{stamp}.csv'
    with backup.open('xb') as file:
        file.write(original)
        file.flush()
        os.fsync(file.fileno())
    temp = None
    try:
        with tempfile.NamedTemporaryFile('wb', dir=CATALOGUE.parent,
                                         prefix='.step73_', suffix='.csv', delete=False) as f:
            temp = Path(f.name)
            f.write(updated)
            f.flush()
            os.fsync(f.fileno())
        # Detect unexpected changes after preview/validation, before replacing.
        if CATALOGUE.read_bytes() != original:
            raise RuntimeError('Catalogue changed during operation; aborting')
        os.replace(temp, CATALOGUE)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()
    audit = OUTPUT / f'step73_exclude_duplicate_{stamp}.json'
    record = {'operation': 'exclude_confirmed_duplicate', 'song_uid': UID,
              'source_pdf': FILENAME, 'before_status': 'include', 'after_status': 'exclude',
              'canonical_song_uid': canonical['song_uid'],
              'canonical_source_pdf': canonical['source_pdf'], 'backup': str(backup),
              'original_sha256': hashlib.sha256(original).hexdigest(),
              'updated_sha256': hashlib.sha256(updated).hexdigest(),
              'source_pdfs_deleted': 0}
    audit.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('APPLIED: 1 status change; all 314 records and source PDFs preserved.')
    print('Backup:', backup)
    print('Audit:', audit)


if __name__ == '__main__':
    main()
