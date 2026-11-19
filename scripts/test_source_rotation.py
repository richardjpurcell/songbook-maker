"""Isolated regression test: rotate one known inverted chart in output only."""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf

BUILDER = Path(__file__).with_name('build_songbook.py')
TARGET = 'Red-Winged Blackbird.pdf'


def first_line_direction(page, label):
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines', []):
            if any(label in span['text'] for span in line['spans']):
                return line['dir']
    raise AssertionError(f'Cannot find {label!r}')


def exercise():
    with tempfile.TemporaryDirectory(prefix='step71_rotation_') as tmp:
        root = Path(tmp)
        for folder in ['scripts', 'data/metadata', 'data/song_sheets', 'output']:
            (root / folder).mkdir(parents=True, exist_ok=True)
        (root / 'scripts/build_songbook.py').write_bytes(BUILDER.read_bytes())
        sheets = root / 'data/song_sheets'
        normal = pymupdf.open()
        sheet = normal.new_page()
        sheet.insert_text((90, 150), 'RED WING BODY TEXT', fontsize=16)
        sheet.insert_text((90, 185), 'G D A D', fontsize=12)
        other = normal.new_page()
        other.insert_text((90, 150), 'SECOND PAGE STAYS UPRIGHT', fontsize=16)
        normal_path = root / 'upright.pdf'
        normal.save(normal_path)
        normal.close()

        # Simulate an actual inverted scan: physically rotate the page
        # *contents*, not the whole page's metadata / output header.
        normal = pymupdf.open(normal_path)
        inverted = pymupdf.open()
        for index in range(len(normal)):
            page = inverted.new_page()
            page.show_pdf_page(page.rect, normal, index, rotate=180 if index == 0 else 0)
        inverted.save(sheets / TARGET)
        inverted.close()
        normal.close()
        control = pymupdf.open()
        page = control.new_page()
        page.insert_text((90, 150), 'CONTROL BODY TEXT', fontsize=16)
        control.save(sheets / 'Control.pdf')
        control.close()

        with (root / 'data/metadata/songs.csv').open('w', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=['song_uid', 'title', 'key', 'status', 'source_pdf', 'position'])
            writer.writeheader()
            writer.writerows([
                dict(song_uid='S00270', title='Red-Winged Blackbird', key='D', status='include', source_pdf=TARGET, position='1'),
                dict(song_uid='S00271', title='Control', key='D', status='include', source_pdf='Control.pdf', position='2'),
            ])
        before = (sheets / TARGET).read_bytes()
        proc = subprocess.run([sys.executable, 'scripts/build_songbook.py'], cwd=root, capture_output=True, text=True)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert (sheets / TARGET).read_bytes() == before, 'Source PDF was altered'
        doc = pymupdf.open(root / 'output/songbook.pdf')
        songs = {name: page-1 for level,name,page in doc.get_toc() if level == 2}
        red = next(i for name,i in songs.items() if 'Red-Winged Blackbird' in name)
        ctl = next(i for name,i in songs.items() if 'Control' in name)
        assert first_line_direction(doc[red], 'RED WING BODY TEXT')[0] > 0.99
        assert first_line_direction(doc[red+1], 'SECOND PAGE STAYS UPRIGHT')[0] > 0.99
        assert first_line_direction(doc[ctl], 'CONTROL BODY TEXT')[0] > 0.99
        assert 'KEY: D' in doc[red].get_text()
        appendix = next(page-1 for level,name,page in doc.get_toc() if name == 'Alphabetical Index')
        contents = next(page-1 for level,name,page in doc.get_toc() if name == 'Table of Contents')
        links = [x['page'] for x in doc[red].get_links() if x['kind'] == pymupdf.LINK_GOTO]
        assert contents in links and appendix in links, links
        report = (root / 'output/build_report.txt').read_text()
        assert 'Source pages rotated: 1' in report, report
        assert 'ROTATED source page: Red-Winged Blackbird.pdf | source page 1 | 180 degrees' in report
        assert 'Unrepresented individual PDFs: 0' in report
        assert 'Included charts: 2' in report
        assert 'Alphabetical index links: 2' in report
        print('PASS: 1 rotated Red-Winged source page; continuation/control upright; source intact; links/report valid')
        doc.close()


if __name__ == '__main__':
    exercise()
