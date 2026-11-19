"""Step 75 synthetic front-matter, version-state and navigation regression.

Never uses the private source PDFs. Run: python scripts/test_front_matter.py
"""
import csv
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent


def build(root):
    proc = subprocess.run([sys.executable, 'scripts/build_songbook.py'],
                          cwd=root, text=True, capture_output=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def make_pdf(path, text, pages=1):
    with pymupdf.open() as doc:
        for number in range(pages):
            doc.new_page().insert_text((80, 132), f'{text} {number + 1}', fontsize=14)
        doc.save(path)


def check_links(page, dest):
    assert any(l['kind'] == pymupdf.LINK_GOTO and l['page'] == dest
               for l in page.get_links()), (page.number, dest, page.get_links())


def exercise():
    with tempfile.TemporaryDirectory(prefix='step75_front_') as directory:
        root = Path(directory)
        for sub in ['scripts', 'data/metadata', 'data/song_sheets', 'output', 'config']:
            (root / sub).mkdir(parents=True)
        shutil.copyfile(HERE / 'build_songbook.py', root / 'scripts/build_songbook.py')
        shutil.copyfile(HERE.parent / 'config/songbook.json', root / 'config/songbook.json')
        sheets = root / 'data/song_sheets'
        make_pdf(sheets / 'Long Sheet.pdf', 'TWO-PAGE-TEST', pages=2)
        make_pdf(sheets / 'Short Sheet.pdf', 'SHORT-TEST')
        make_pdf(sheets / 'Excluded Sheet.pdf', 'EXCLUDED-TEST')
        make_pdf(sheets / 'Review Sheet.pdf', 'REVIEW-TEST')
        fields = ['song_uid', 'title', 'key', 'status', 'source_pdf', 'position']
        rows = [
            ['S00001', 'The Song', 'G', 'include', 'Long Sheet.pdf', '1'],
            ['S00002', 'The Song (alternate)', 'C', 'include', 'Short Sheet.pdf', '2'],
            ['S00003', 'Excluded Tune', 'C', 'exclude', 'Excluded Sheet.pdf', '3'],
            ['S00004', 'Unreviewed Tune', 'Unknown', 'review', 'Review Sheet.pdf', '4'],
        ]
        catalogue = root / 'data/metadata/songs.csv'
        with catalogue.open('w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(fields)
            writer.writerows(rows)
        build(root)
        state_path = root / 'output/publication_state.json'
        first = json.loads(state_path.read_text())
        assert first['schema'] == 1 and first['major_version'] == 1 and first['revision'] == 0
        with pymupdf.open(root / 'output/songbook.pdf') as book:
            assert len(book) == 2 + 1 + 4 + 1, len(book)
            assert 'Jubilee Road Songbook' in book[0].get_text()
            assert 'Version 1.0' in book[0].get_text()
            assert 'Last updated:' in book[0].get_text()
            guide = book[1].get_text()
            assert 'github.com/richardjpurcell/songbook-maker' in guide
            assert 'Source PDFs and generated songbooks remain private and local.' in guide
            repository_links = [link for link in book[1].get_links()
                                if link['kind'] == pymupdf.LINK_URI]
            assert len(repository_links) == 1, repository_links
            assert repository_links[0]['uri'] == 'https://github.com/richardjpurcell/songbook-maker'
            assert 0 <= repository_links[0]['from'].x0 < repository_links[0]['from'].x1 <= 612
            for phrase in ('How to use this songbook', 'Key Contents', 'Alphabetical Index',
                           'clickable', 'same song', 'Song_Title_Optional_Version_Key.pdf',
                           'Midnight_Special_Regular_Chorus_G.pdf',
                           'the catalogue determines title, key, and inclusion status'):
                assert phrase in guide, (phrase, guide)
            report = (root / 'output/build_report.txt').read_text()
            for phrase in ('Front matter pages: 2', 'Title pages: 1', 'Guide pages: 1',
                           'TOC pages: 1', 'Alphabetical index pages: 1',
                           'Alphabetical index links: 3', 'Unreviewed PDFs included: 1',
                           'Unrepresented individual PDFs: 0'):
                assert phrase in report, phrase
            toc = book.get_toc()
            assert [(level, name, pg) for level, name, pg in toc[:3]] == [
                (1, 'Title Page', 1), (1, 'About This Songbook', 2),
                (1, 'Table of Contents', 3)]
            toc_start = next(pg - 1 for level, name, pg in toc if name == 'Table of Contents')
            alpha_start = next(pg - 1 for level, name, pg in toc if name == 'Alphabetical Index')
            assert toc_start == 2 and alpha_start == 7
            charts = [pg - 1 for level, name, pg in toc if level == 2]
            assert len(charts) == 3
            check_links(book[0], toc_start)
            check_links(book[1], toc_start)
            check_links(book[1], alpha_start)
            check_links(book[toc_start], alpha_start)
            for page_number in [charts[0], charts[0] + 1, charts[1], charts[2]]:
                check_links(book[page_number], toc_start)
                check_links(book[page_number], alpha_start)
            all_targets = [l['page'] for l in book[alpha_start].get_links()
                           if l['kind'] == pymupdf.LINK_GOTO and l['page'] != toc_start]
            assert set(all_targets) == set(charts) and len(all_targets) == len(charts)
            check_links(book[alpha_start], toc_start)
            assert 'EXCLUDED-TEST' not in '\n'.join(p.get_text() for p in book)
            for page in book:
                for link in page.get_links():
                    if link['kind'] == pymupdf.LINK_GOTO:
                        assert 0 <= link['page'] < len(book), link
            # Check all text stays within printable letter pages.
            for index in [0, 1]:
                for block in book[index].get_text('dict')['blocks']:
                    if block['type'] == 0:
                        x0, y0, x1, y1 = block['bbox']
                        assert 0 <= x0 < x1 <= 612 and 0 <= y0 < y1 <= 792, block
        build(root)
        assert json.loads(state_path.read_text()) == first, 'Unchanged build altered version/date'
        # A changed source chart affects the publication and increments the edition.
        make_pdf(sheets / 'Short Sheet.pdf', 'UPDATED-SHORT')
        build(root)
        second = json.loads(state_path.read_text())
        assert second['revision'] == 1 and second['fingerprint'] != first['fingerprint']
        assert 'Version 1.1' in pymupdf.open(root / 'output/songbook.pdf')[0].get_text()
        build(root)
        assert json.loads(state_path.read_text()) == second
        # Title changes only through configuration; this also advances the edition.
        config = root / 'config/songbook.json'
        config.write_text(json.dumps({'title': 'Custom Title', 'major_version': 1}) + '\n')
        build(root)
        assert 'Custom Title' in pymupdf.open(root / 'output/songbook.pdf')[0].get_text()
        assert json.loads(state_path.read_text())['revision'] == 2
    print('PASS: title/guide, complete link offsets, printable layout, revision stability,')
    print('      source-change and configuration-change edition increments')


if __name__ == '__main__':
    exercise()
