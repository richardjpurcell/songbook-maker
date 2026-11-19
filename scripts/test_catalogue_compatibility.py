"""Build using actual catalogue metadata but ONLY synthetic temporary chart PDFs.

Validates the current catalogue schema and exclusions without distributing PDFs.
Run: python scripts/test_catalogue_compatibility.py
"""
import csv
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]


def exercise():
    source_catalogue = ROOT / 'data/metadata/songs.csv'
    with source_catalogue.open(newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    expected_count = len(rows)
    expected_curated = sum(r['status'].strip().lower() == 'include' for r in rows)
    assert expected_count > 0 and expected_curated > 0
    with tempfile.TemporaryDirectory(prefix='step75_catalogue_compatibility_') as directory:
        root = Path(directory)
        for folder in ('scripts', 'data/metadata', 'data/song_sheets', 'output', 'config'):
            (root / folder).mkdir(parents=True)
        (root / 'data/metadata/songs.csv').write_bytes(source_catalogue.read_bytes())
        shutil.copyfile(ROOT / 'scripts/build_songbook.py', root / 'scripts/build_songbook.py')
        config = ROOT / 'config/songbook.json'
        if config.is_file():
            shutil.copyfile(config, root / 'config/songbook.json')
        filenames = {r['source_pdf'] for r in rows if r['status'].strip() == 'include'}
        filenames.add('Stand My Ground.pdf')  # original Step 73 guard
        for name in filenames:
            if not name:
                continue
            with pymupdf.open() as pdf:
                pdf.new_page().insert_text((90, 150), 'SYNTHETIC-COMPATIBILITY-CHART')
                pdf.save(root / 'data/song_sheets' / name)
        result = subprocess.run([sys.executable, 'scripts/build_songbook.py'],
                                cwd=root, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        with pymupdf.open(root / 'output/songbook.pdf') as pdf:
            toc = pdf.get_toc()
            chart_count = sum(level == 2 for level, _, _ in toc)
            assert chart_count == expected_curated, (chart_count, expected_curated)
            assert 'Jubilee Road Songbook' in pdf[0].get_text()
            alpha = next(page-1 for level, name, page in toc if name == 'Alphabetical Index')
            tocstart = next(page-1 for level, name, page in toc if name == 'Table of Contents')
            chart_starts = {page - 1 for level, name, page in toc if level == 2}
            assert tocstart == 2 and len(chart_starts) == expected_curated
            targets = [link['page'] for page in list(pdf)[alpha:] for link in page.get_links()
                       if link['kind'] == pymupdf.LINK_GOTO and link['page'] in chart_starts]
            assert len(targets) == expected_curated and set(targets) == chart_starts
        report = (root / 'output/build_report.txt').read_text()
        for expected in (f'Catalogue entries: {expected_count}',
                         f'Curated charts: {expected_curated}',
                         'Unreviewed PDFs included: 0',
                         f'Alphabetical index links: {expected_curated}',
                         'Front matter pages: 2'):
            assert expected in report, (expected, report)
    print(f'PASS: {expected_count} catalogue records and {expected_curated} curated index entries,')
    print('      all synthesized locally without opening a private song-sheet PDF')


if __name__ == '__main__':
    exercise()
