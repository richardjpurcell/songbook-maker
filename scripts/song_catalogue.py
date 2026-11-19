"""Guarded CSV catalogue operations shared by add_song and remove_song.

Catalogue files alone are modified. Source PDFs are never opened for writing.
Backups and audits are written beneath output/ (ignored by Git).
"""
import csv
import datetime as dt
import hashlib
import io
import json
import os
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / 'data' / 'metadata' / 'songs.csv'
SHEETS = ROOT / 'data' / 'song_sheets'
OUTPUT = ROOT / 'output'
REQUIRED = {'song_uid', 'title', 'key', 'status', 'source_pdf', 'position'}
UID_PATTERN = re.compile(r'S\d{5,}\Z')
KEY_PATTERN = re.compile(r'[A-G](?:#|b)?m?\Z')


def load_catalogue():
    if not CATALOGUE.is_file() or CATALOGUE.is_symlink():
        raise ValueError(f'Expected a regular catalogue CSV: {CATALOGUE}')
    original = CATALOGUE.read_bytes()
    try:
        with io.StringIO(original.decode('utf-8-sig'), newline='') as stream:
            reader = csv.DictReader(stream)
            fields = reader.fieldnames or []
            if not fields or len(fields) != len(set(fields)):
                raise ValueError('Missing or duplicated catalogue column names')
            if not REQUIRED.issubset(fields):
                raise ValueError(f'Missing catalogue columns: {sorted(REQUIRED - set(fields))}')
            rows = list(reader)
    except UnicodeError as exc:
        raise ValueError('Catalogue must be UTF-8 CSV') from exc
    if not rows:
        raise ValueError('Catalogue contains no records')
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError('Malformed catalogue row: missing or extra CSV fields')
    uids = [(r['song_uid'] or '').strip() for r in rows]
    if any(not UID_PATTERN.fullmatch(u) for u in uids):
        raise ValueError('Every existing song_uid must match S plus at least five digits')
    if len(uids) != len(set(uids)):
        raise ValueError('Duplicate permanent song_uid in the catalogue')
    return original, fields, rows


def encode_catalogue(original, fields, rows):
    newline = '\r\n' if b'\r\n' in original else '\n'
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator=newline, extrasaction='raise')
    writer.writeheader()
    writer.writerows(rows)
    prefix = b'\xef\xbb\xbf' if original.startswith(b'\xef\xbb\xbf') else b''
    result = prefix + output.getvalue().encode('utf-8')
    with io.StringIO(result.decode('utf-8-sig'), newline='') as verify:
        assert list(csv.DictReader(verify)) == rows
    return result


def checked_pdf_path(filename):
    if (not filename or Path(filename).name != filename or '/' in filename or
            '\\' in filename or filename in ('.', '..') or Path(filename).suffix.lower() != '.pdf'):
        raise ValueError('Source PDF must be a single .pdf filename, not a path')
    path = SHEETS / filename
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'Source PDF not found as a regular local file: {filename}')
    if path.resolve().parent != SHEETS.resolve():
        raise ValueError('Source PDF must remain inside data/song_sheets')
    return path


def write_change(action, original, fields, rows, detail):
    """Write backup/audit first; atomically replace CSV after verification.

    A failing preflight or backup leaves CSV unchanged. The audit includes the
    old and new checksums and identifies the untouched source filename.
    """
    updated = encode_catalogue(original, fields, rows)
    if updated == original:
        raise ValueError('No catalogue change requested')
    stamp = dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup_dir = OUTPUT / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f'songs_before_{action}_{stamp}.csv'
    audit_path = OUTPUT / f'{action}_{stamp}.json'
    payload = {
        'action': action,
        'timestamp': dt.datetime.now().astimezone().isoformat(timespec='seconds'),
        'change': detail,
        'catalogue_records_after': len(rows),
        'backup': str(backup_path),
        'before_sha256': hashlib.sha256(original).hexdigest(),
        'after_sha256': hashlib.sha256(updated).hexdigest(),
        'source_pdfs_modified': False,
        'source_pdfs_deleted': False,
    }
    staged_csv = staged_audit = None
    try:
        with backup_path.open('xb') as f:
            f.write(original)
            f.flush()
            os.fsync(f.fileno())
        with tempfile.NamedTemporaryFile('wb', dir=CATALOGUE.parent,
                                         prefix='.song_catalogue_', suffix='.csv',
                                         delete=False) as f:
            staged_csv = Path(f.name)
            f.write(updated)
            f.flush()
            os.fsync(f.fileno())
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=OUTPUT,
                                         prefix='.song_audit_', suffix='.json',
                                         delete=False) as f:
            staged_audit = Path(f.name)
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        if CATALOGUE.read_bytes() != original:
            raise RuntimeError('Catalogue changed during operation; refusing to overwrite it')
        # Once the replace succeeds, leave the prior state available in backup.
        os.replace(staged_csv, CATALOGUE)
        staged_csv = None
        os.replace(staged_audit, audit_path)
        staged_audit = None
    finally:
        for temporary in (staged_csv, staged_audit):
            if temporary is not None and temporary.exists():
                temporary.unlink()
    return backup_path, audit_path
