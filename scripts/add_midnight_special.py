#!/usr/bin/env python3
"""Guarded addition of Midnight Special (Regular Chorus), key G.

Run from any directory:
    python scripts/add_midnight_special.py --check
    python scripts/add_midnight_special.py --apply

Edits only data/metadata/songs.csv; preserves the original PDF locally.
"""
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import os
import re
import tempfile
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / 'data' / 'metadata' / 'songs.csv'
SHEETS = ROOT / 'data' / 'song_sheets'
OUTPUT = ROOT / 'output'
FILENAME = 'Midnight_Special_Regular_Chorus_G.pdf'
TITLE = 'Midnight Special (Regular Chorus)'
KEY = 'G'


def prepare():
    if not CATALOGUE.is_file():
        raise ValueError(f'Catalogue missing: {CATALOGUE}')
    path = SHEETS / FILENAME
    if not path.is_file() or path.is_symlink():
        raise ValueError(f'Expected a local, regular PDF: {path}')
    with pymupdf.open(path) as pdf:
        if not pdf.is_pdf or pdf.page_count < 1 or pdf.needs_pass:
            raise ValueError('Source file must be an unencrypted, nonempty PDF')
        pages = pdf.page_count
    original = CATALOGUE.read_bytes()
    with CATALOGUE.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        rows = list(reader)
    required = {'song_uid', 'title', 'key', 'status', 'source_pdf', 'position'}
    if not required.issubset(fields):
        raise ValueError(f'Missing required columns: {sorted(required - set(fields))}')
    if not rows:
        raise ValueError('Catalogue is empty')
    if any(r.get(None) is not None for r in rows):
        raise ValueError('Malformed CSV: surplus fields')
    # Never register the same PDF, or an apparent second copy of this title.
    if any((r['source_pdf'] or '').strip().casefold() == FILENAME.casefold() for r in rows):
        raise ValueError('The source filename is already present in the catalogue; no changes made')
    if any((r['title'] or '').strip().casefold() == TITLE.casefold() for r in rows):
        raise ValueError('This arrangement title is already present in the catalogue; review manually')
    used_uids = [(r['song_uid'] or '').strip() for r in rows]
    if len(set(used_uids)) != len(used_uids) or any(not re.fullmatch(r'S\d{5,}', u) for u in used_uids):
        raise ValueError('Catalogue contains invalid or duplicate permanent UIDs')
    uid_number = max(int(uid[1:]) for uid in used_uids) + 1
    uid = f'S{uid_number:05d}'
    if uid in used_uids:
        raise ValueError('UID collision')
    g_positions = []
    for row in rows:
        if row['key'].strip() == KEY and row['status'].strip().lower() in ('include', 'placeholder'):
            p = (row.get('position') or '').strip()
            if p:
                try:
                    g_positions.append(int(p))
                except ValueError:
                    raise ValueError(f'Noninteger position in G section: {p!r}')
    position = max(g_positions, default=0) + 1
    new = {field: '' for field in fields}
    new.update(song_uid=uid, title=TITLE, key=KEY, status='include',
               source_pdf=FILENAME, position=str(position))
    # Legacy 'id' is not the active display ID. The builder assigns G### at build time.
    rows.append(new)
    return original, fields, rows, new, pages


def serialize(fields, rows, original):
    line_ending = '\r\n' if b'\r\n' in original else '\n'
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator=line_ending)
    writer.writeheader()
    writer.writerows(rows)
    bom = b'\xef\xbb\xbf' if original.startswith(b'\xef\xbb\xbf') else b''
    result = bom + stream.getvalue().encode('utf-8')
    with io.StringIO(result.decode('utf-8-sig'), newline='') as f:
        assert list(csv.DictReader(f)) == rows
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true', help='Validate and preview without writing')
    group.add_argument('--apply', action='store_true', help='Back up and append one catalogue row')
    args = parser.parse_args()
    try:
        original, fields, rows, entry, pages = prepare()
    except Exception as exc:
        parser.error(f'Validation failed; no changes made: {exc}')
    print('ADD MIDNIGHT SPECIAL — ' + ('PREVIEW' if args.check else 'APPLY'))
    print(f"New record: {entry['song_uid']} | {entry['title']} | key {KEY} | position {entry['position']}")
    print(f'Source PDF: {FILENAME} ({pages} page(s))')
    print(f'Catalogue records: {len(rows)-1} -> {len(rows)}')
    print('Only the catalogue CSV will change; source PDF remains local and unmodified.')
    if args.check:
        print('PREVIEW ONLY — no files changed.')
        return
    updated = serialize(fields, rows, original)
    backup_dir = OUTPUT / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = backup_dir / f'songs_before_midnight_special_{stamp}.csv'
    with backup.open('xb') as f:
        f.write(original)
        f.flush()
        os.fsync(f.fileno())
    temp = None
    try:
        with tempfile.NamedTemporaryFile('wb', dir=CATALOGUE.parent,
                                         prefix='.add_midnight_special_', suffix='.csv',
                                         delete=False) as f:
            temp = Path(f.name)
            f.write(updated)
            f.flush()
            os.fsync(f.fileno())
        if CATALOGUE.read_bytes() != original:
            raise RuntimeError('Catalogue changed since validation; nothing replaced')
        os.replace(temp, CATALOGUE)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()
    audit = OUTPUT / f'add_midnight_special_{stamp}.json'
    audit.write_text(json.dumps({
        'action': 'add_song', 'entry': entry, 'source_pdf_pages': pages,
        'backup': str(backup),
        'before_sha256': hashlib.sha256(original).hexdigest(),
        'after_sha256': hashlib.sha256(updated).hexdigest(),
        'source_pdf_modified': False,
    }, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('APPLIED: one new catalogue record.')
    print('Backup:', backup)
    print('Audit:', audit)


if __name__ == '__main__':
    main()
