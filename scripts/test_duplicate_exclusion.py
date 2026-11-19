"""Isolated Step 73 regression: preview / guard / apply / rebuilt indexes."""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent


def execute(root, script, option=None):
    command = [sys.executable, f'scripts/{script}'] + ([option] if option else [])
    return subprocess.run(command, cwd=root, capture_output=True, text=True)


def main():
    with tempfile.TemporaryDirectory(prefix='step73_duplicate_') as d:
        root = Path(d)
        for folder in ('scripts', 'data/metadata', 'data/song_sheets', 'output'):
            (root / folder).mkdir(parents=True, exist_ok=True)
        for file in ('build_songbook.py', 'exclude_step73_duplicate.py'):
            (root / 'scripts' / file).write_bytes((HERE / file).read_bytes())
        rows = []
        cols = ['id', 'song_uid', 'title', 'key', 'status', 'source_pdf', 'toc_entry', 'position', 'capo_fret', 'chord_shapes_key']
        for n in range(1, 315):
            if n == 289:
                title, filename, status = 'Stand My Ground', 'Stand My Ground.pdf', 'include'
            elif n == 24:
                title, filename, status = "I Won’t Back Down (Tom Petty)", 'I Won_t Back Down.pdf', 'include'
            else:
                title, filename, status = f'Sample Song {n:03}', f'sample_{n:03}.pdf', ('include' if n <= 209 else 'review')
            rows.append({'id': f'X{n:03}', 'song_uid': f'S{n:05}', 'title': title,
                         'key': 'G', 'status': status, 'source_pdf': filename,
                         'toc_entry': title, 'position': str(n), 'capo_fret': '', 'chord_shapes_key': ''})
        # The 208 filler rows + canonical + duplicate = 210 included.
        assert sum(r['status'] == 'include' for r in rows) == 210
        sheets = root / 'data/song_sheets'
        for r in rows:
            if r['status'] != 'include':
                continue
            doc = pymupdf.open()
            doc.new_page().insert_text((50, 130), f"CHART {r['song_uid']}")
            doc.save(sheets / r['source_pdf'])
            doc.close()
        catalogue = root / 'data/metadata/songs.csv'
        with catalogue.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        before = catalogue.read_bytes()
        result = execute(root, 'exclude_step73_duplicate.py', '--check')
        assert result.returncode == 0, result.stderr
        assert 'expected after: 209' in result.stdout
        assert catalogue.read_bytes() == before
        # Builder must reject a premature replace before the catalogue exclusion.
        premature = execute(root, 'build_songbook.py')
        assert premature.returncode != 0 and 'must be status=exclude' in premature.stderr
        result = execute(root, 'exclude_step73_duplicate.py', '--apply')
        assert result.returncode == 0, result.stdout + result.stderr
        with catalogue.open(newline='', encoding='utf-8') as f:
            after = list(csv.DictReader(f))
        assert sum(r['status'] == 'include' for r in after) == 209
        for old, new in zip(rows, after):
            assert {k for k in cols if old[k] != new[k]} == ({'status'} if old['song_uid'] == 'S00289' else set())
        assert (sheets / 'Stand My Ground.pdf').is_file()
        again = execute(root, 'exclude_step73_duplicate.py', '--apply')
        assert again.returncode != 0
        build = execute(root, 'build_songbook.py')
        assert build.returncode == 0, build.stdout + build.stderr
        with pymupdf.open(root / 'output/songbook.pdf') as book:
            toc = book.get_toc()
            charts = [(name, p - 1) for lvl, name, p in toc if lvl == 2]
            assert len(charts) == 209
            assert all('Stand My Ground' not in name for name, _ in charts)
            assert sum("I Won't Back Down" in name for name, _ in charts) == 1
            alpha = next(p-1 for level, name, p in toc if name == 'Alphabetical Index')
            destinations = {page for _, page in charts}
            assert sum(1 for page in list(book)[alpha:] for l in page.get_links()
                       if l['kind'] == pymupdf.LINK_GOTO and l.get('page') in destinations) == 209
        report = (root / 'output/build_report.txt').read_text()
        for line in ['Included charts: 209', 'Unreviewed PDFs included: 0',
                     'Alphabetical index links: 209', 'Unrepresented individual PDFs: 0',
                     'Excluded duplicate PDFs: 1']:
            assert line in report, (line, report)
        print('PASS: preview leaves catalogue unchanged; strict exclusion guard; one status change;')
        print('      duplicate source retained; 209 valid chart/appendix entries; no unreviewed PDFs')


if __name__ == '__main__':
    main()
