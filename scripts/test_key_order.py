"""Synthetic regression for alphabetically ordered key sections and PDF links."""
import csv
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf

BUILDER = Path(__file__).with_name('build_songbook.py')
KEYS = ['A', 'Am', 'B', 'Bm', 'C', 'D', 'Dm', 'E', 'Em',
        'F', 'F#', 'F#m', 'G', 'Unknown']


def make_pdf(path, text):
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((70, 130), text, fontsize=12)
        pdf.save(path)


def test():
    with tempfile.TemporaryDirectory(prefix='songbook_key_order_') as tmp:
        root = Path(tmp)
        for folder in ['scripts', 'data/metadata', 'data/song_sheets', 'output']:
            (root / folder).mkdir(parents=True)
        shutil.copyfile(BUILDER, root / 'scripts/build_songbook.py')
        rows = []
        for index, key in enumerate(reversed(KEYS), 1):
            filename = f'chart_{index:02d}.pdf'
            title = 'A later arrangement' if key == 'A' else f'{key} chart'
            rows.append({'song_uid': f'S{index:05d}', 'key': key,
                         'title': title, 'status': 'include',
                         'source_pdf': filename, 'position': '9' if key == 'A' else '1'})
            make_pdf(root / 'data/song_sheets' / filename, f'SYNTHETIC:{key}')
        rows.append({'song_uid': 'S00015', 'key': 'A', 'title': 'A earlier arrangement',
                     'status': 'include', 'source_pdf': 'A_early.pdf', 'position': '2'})
        make_pdf(root / 'data/song_sheets/A_early.pdf', 'SYNTHETIC:A-EARLY')
        make_pdf(root / 'data/song_sheets/unlisted.pdf', 'SYNTHETIC:UNREVIEWED')
        with (root / 'data/metadata/songs.csv').open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        result = subprocess.run([sys.executable, 'scripts/build_songbook.py'],
                                cwd=root, text=True, capture_output=True)
        assert result.returncode == 0, result.stdout + result.stderr
        with pymupdf.open(root / 'output/songbook.pdf') as pdf:
            outline = pdf.get_toc()
            headings = [name for level, name, _ in outline if level == 1
                        and (name.startswith('Key of ') or name in ('Unknown Key', 'Unreviewed PDFs'))]
            assert headings == [f'Key of {key}' for key in KEYS[:-1]] + ['Unknown Key', 'Unreviewed PDFs'], headings
            chart_pages = [page - 1 for level, _, page in outline if level == 2]
            toc_pages = range(2, min(chart_pages))
            contents = '\n'.join(pdf[p].get_text() for p in toc_pages)
            assert re.findall(r'^KEY:\s*(\S+)\s*$', contents, re.M) == KEYS
            assert contents.index('KEY: Unknown') < contents.index('Unreviewed PDFs')
            assert contents.index('A001   A earlier arrangement') < contents.index('A002   A later arrangement')
            alpha = next(page - 1 for level, title, page in outline if title == 'Alphabetical Index')
            starts = set(chart_pages)
            for pages in (toc_pages, range(alpha, len(pdf))):
                targets = [link['page'] for p in pages for link in pdf[p].get_links()
                           if link['kind'] == pymupdf.LINK_GOTO and link['page'] in starts]
                assert len(targets) == len(rows) + 1 and set(targets) == starts
            for p in chart_pages:
                targets = {link['page'] for link in pdf[p].get_links() if link['kind'] == pymupdf.LINK_GOTO}
                assert 2 in targets and alpha in targets, (p, targets)
            assert 'SYNTHETIC:A-EARLY' in pdf[chart_pages[0]].get_text()
        report = (root / 'output/build_report.txt').read_text()
        assert 'Unreviewed PDFs included: 1' in report
    print('PASS: alphabetically ordered keys, Unknown and Unreviewed last; catalogue positions retained')
    print('PASS: all TOC/appendix destinations, chart return links and bookmarks; synthetic PDFs only')


if __name__ == '__main__':
    test()
