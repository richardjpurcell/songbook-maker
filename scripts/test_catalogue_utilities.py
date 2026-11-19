"""Step 75 synthetic end-to-end tests of guarded add/remove and general exclusion.

Creates temporary PDFs and CSV only. Never uses private song-sheet PDFs.
Run: python scripts/test_catalogue_utilities.py
"""
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent
FIELDS = ['song_uid', 'id', 'key', 'position', 'toc_entry', 'title', 'artist',
          'status', 'source_pdf', 'key_source', 'capo_fret', 'chord_shapes_key']


def make_pdf(path, phrase):
    with pymupdf.open() as doc:
        doc.new_page().insert_text((80, 155), phrase, fontsize=14)
        doc.save(path)


def command(root, script, *args, succeeds=True):
    proc = subprocess.run([sys.executable, f'scripts/{script}', *args],
                          cwd=root, text=True, capture_output=True)
    if succeeds:
        assert proc.returncode == 0, proc.stdout + proc.stderr
    else:
        assert proc.returncode != 0, proc.stdout + proc.stderr
    return proc.stdout + proc.stderr


def read_records(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def exercise():
    with tempfile.TemporaryDirectory(prefix='step75_catalogue_') as directory:
        root = Path(directory)
        for folder in ['scripts', 'data/metadata', 'data/song_sheets', 'output', 'config']:
            (root / folder).mkdir(parents=True)
        for script in ['add_song.py', 'remove_song.py', 'song_catalogue.py', 'build_songbook.py', 'sync_catalogue.py']:
            shutil.copyfile(HERE / script, root / 'scripts' / script)
        shutil.copyfile(HERE.parent / 'config/songbook.json', root / 'config/songbook.json')
        sheets = root / 'data/song_sheets'
        pdf_data = {
            'Original.pdf': 'ORIGINAL-SYNTHETIC',
            'Review Sheet.pdf': 'REVIEW-SYNTHETIC',
            'Stand My Ground.pdf': 'OLD-DUPLICATE-SYNTHETIC',
            'Excluded Source.pdf': 'EXCLUDED-SYNTHETIC',
            'Uncatalogued Sheet.pdf': 'UNCATALOGUED-SYNTHETIC',
            "O'Brien's Tune_G.pdf": 'APOSTROPHE-SYNTHETIC',
        }
        for filename, marker in pdf_data.items():
            make_pdf(sheets / filename, marker)
        original_sheets = {name: hashlib.sha256((sheets / name).read_bytes()).hexdigest()
                           for name in pdf_data}
        rows = []
        for uid, title, key, status, name in [
            ('S00001', 'Original', 'G', 'include', 'Original.pdf'),
            ('S00002', 'Held arrangement', 'Unknown', 'review', 'Review Sheet.pdf'),
            ('S00289', 'Stand My Ground', 'Unknown', 'exclude', 'Stand My Ground.pdf'),
            ('S00290', 'Excluded arrangement', 'G', 'exclude', 'Excluded Source.pdf'),
        ]:
            entry = dict.fromkeys(FIELDS, '')
            entry.update(song_uid=uid, title=title, key=key, status=status,
                         source_pdf=name, position='5', toc_entry=title)
            rows.append(entry)
        csv_path = root / 'data/metadata/songs.csv'
        # Test preserving UTF-8 BOM and CRLF when editing in both utilities.
        with csv_path.open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator='\r\n')
            writer.writeheader()
            writer.writerows(rows)
        old_bytes = csv_path.read_bytes()
        assert old_bytes.startswith(b'\xef\xbb\xbf') and b'\r\n' in old_bytes

        extra = ['--pdf', "O'Brien's Tune_G.pdf", '--title', 'Original', '--key', 'G',
                 '--artist', "O'Brien", '--check']
        preview = command(root, 'add_song.py', *extra)
        assert 'S00291' in preview and 'Existing arrangement' in preview
        assert csv_path.read_bytes() == old_bytes
        assert not list((root / 'output').rglob('*.json'))
        command(root, 'add_song.py', *extra[:-1], '--apply')
        newer = read_records(csv_path)
        assert len(newer) == 5 and newer[:-1] == rows
        added = newer[-1]
        assert added['song_uid'] == 'S00291' and added['status'] == 'include'
        assert added['source_pdf'] == "O'Brien's Tune_G.pdf"
        assert added['position'] == '6' and added['artist'] == "O'Brien"
        assert csv_path.read_bytes().startswith(b'\xef\xbb\xbf')
        assert b'\r\n' in csv_path.read_bytes()
        backup = list((root / 'output/backups').glob('songs_before_add_song_*.csv'))
        audit = list((root / 'output').glob('add_song_*.json'))
        assert len(backup) == len(audit) == 1
        assert backup[0].read_bytes() == old_bytes
        record = json.loads(audit[0].read_text())
        assert record['change']['song']['song_uid'] == 'S00291'
        assert record['source_pdfs_modified'] is False
        command(root, 'sync_catalogue.py')  # legacy import still handles blank display IDs
        command(root, 'add_song.py', *extra[:-1], '--apply', succeeds=False)
        for disallowed in ('Excluded Source.pdf', 'Original.pdf'):
            command(root, 'add_song.py', '--pdf', disallowed, '--title', 'Variation',
                    '--key', 'G', '--apply', succeeds=False)
        command(root, 'add_song.py', '--pdf', 'not present.pdf', '--title', 'Missing',
                '--key', 'G', '--apply', succeeds=False)
        command(root, 'add_song.py', '--pdf', '../Original.pdf', '--title', 'Unsafe',
                '--key', 'G', '--apply', succeeds=False)
        command(root, 'add_song.py', '--pdf', 'Original.pdf', '--title', 'Bad key',
                '--key', 'H', '--apply', succeeds=False)
        assert read_records(csv_path) == newer

        # New chart appears in both indexes before removal.
        command(root, 'build_songbook.py')
        with pymupdf.open(root / 'output/songbook.pdf') as book:
            assert 'APOSTROPHE-SYNTHETIC' in '\n'.join(p.get_text() for p in book)
            charts = [text for level, text, _ in book.get_toc() if level == 2]
            assert sum('Original' in text for text in charts) == 2

        preview = command(root, 'remove_song.py', '--uid', 'S00291', '--check')
        assert "O'Brien's Tune_G.pdf" in preview and 'include -> exclude' in preview
        assert read_records(csv_path) == newer
        before_remove = csv_path.read_bytes()
        command(root, 'remove_song.py', '--uid', 'S00291', '--apply')
        final = read_records(csv_path)
        assert final[:-1] == rows
        assert final[-1] == dict(added, status='exclude')
        removed_audit = list((root / 'output').glob('remove_song_*.json'))
        removed_backup = list((root / 'output/backups').glob('songs_before_remove_song_*.csv'))
        assert len(removed_audit) == len(removed_backup) == 1
        assert removed_backup[0].read_bytes() == before_remove
        assert json.loads(removed_audit[0].read_text())['change']['new_status'] == 'exclude'
        command(root, 'remove_song.py', '--uid', 'S00291', '--apply', succeeds=False)
        command(root, 'remove_song.py', '--uid', 'S99999', '--apply', succeeds=False)
        command(root, 'remove_song.py', '--uid', 'G001', '--apply', succeeds=False)
        command(root, 'remove_song.py', '--uid', 'S00002', '--apply', succeeds=False)
        assert read_records(csv_path) == final
        command(root, 'build_songbook.py')
        with pymupdf.open(root / 'output/songbook.pdf') as book:
            text = '\n'.join(page.get_text() for page in book)
            for marker in ('ORIGINAL-SYNTHETIC', 'REVIEW-SYNTHETIC', 'UNCATALOGUED-SYNTHETIC'):
                assert marker in text
            for marker in ('APOSTROPHE-SYNTHETIC', 'OLD-DUPLICATE-SYNTHETIC', 'EXCLUDED-SYNTHETIC'):
                assert marker not in text
            assert len([1 for level, _, _ in book.get_toc() if level == 2]) == 3
        report = (root / 'output/build_report.txt').read_text()
        assert 'Curated charts: 1' in report
        assert 'Unreviewed PDFs included: 2' in report
        assert 'Unrepresented individual PDFs: 0' in report
        assert 'Intentionally excluded source PDFs: 3' in report
        for name, old_hash in original_sheets.items():
            assert hashlib.sha256((sheets / name).read_bytes()).hexdigest() == old_hash
        # Duplicate UIDs fail closed, without changing any catalogue files.
        corrupt = final + [dict(final[0], source_pdf='Other.pdf')]
        with csv_path.open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(corrupt)
        tampered = csv_path.read_bytes()
        command(root, 'add_song.py', *extra[:-1], '--apply', succeeds=False)
        command(root, 'remove_song.py', '--uid', 'S00001', '--apply', succeeds=False)
        assert csv_path.read_bytes() == tampered
    print('PASS: add/remove preview and apply, backups/audits, BOM/CRLF, permanent IDs,')
    print('      duplicate safeguards, spaces/apostrophes, general exclusion, PDF privacy')


if __name__ == '__main__':
    exercise()
