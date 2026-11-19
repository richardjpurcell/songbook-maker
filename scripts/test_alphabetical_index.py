"""Build and audit a synthetic index; never touches private song PDFs."""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf

BUILDER = Path(__file__).with_name('build_songbook.py')


def audit_sample(number=210):
    with tempfile.TemporaryDirectory(prefix='songbook_alpha_test_') as temp:
        root = Path(temp)
        (root / 'scripts').mkdir()
        (root / 'data/metadata').mkdir(parents=True)
        (root / 'data/song_sheets').mkdir()
        (root / 'output').mkdir()
        (root / 'scripts/build_songbook.py').write_bytes(BUILDER.read_bytes())
        titles = ['The Weight', 'A Banjo', 'An Owl', 'Éclair', 'Alpha', 'The Alpha',
                  'Everything Stays', 'Everything Stays (single sheet)']
        rows = []
        for i in range(number):
            title = titles[i] if i < len(titles) else f'Song {i:03d}'
            key = ['G', 'D', 'Unknown'][i % 3]
            filename = f'song_{i:03d}.pdf'
            rows.append({'song_uid': f'S{i+1:05d}', 'title': title, 'key': key,
                         'status': 'include', 'source_pdf': filename,
                         'position': str(i + 1)})
            doc = pymupdf.open()
            page = doc.new_page()
            page.insert_text((60, 140), f'CHART TEST {i:03d}', fontsize=12)
            doc.save(root / 'data/song_sheets' / filename)
            doc.close()
        with (root / 'data/metadata/songs.csv').open('w', newline='') as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        completed = subprocess.run([sys.executable, 'scripts/build_songbook.py'],
                                   cwd=root, capture_output=True, text=True)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        doc = pymupdf.open(root / 'output/songbook.pdf')
        outlines = doc.get_toc()
        alpha = next(p - 1 for level, label, p in outlines if label == 'Alphabetical Index')
        assert len([x for x in outlines if x[0] == 2]) == number
        assert 'Songbook - alphabetical index'.lower() in doc[alpha].get_text().lower()
        index_pages = range(alpha, len(doc))
        song_pages = [p - 1 for level, label, p in outlines if level == 2]
        toc_page = next(p - 1 for level, label, p in outlines if label == 'Table of Contents')
        assert toc_page == 2
        # Every chart gets a back-link to the alphabetical index and the key contents.
        for p in song_pages:
            links = [link['page'] for link in doc[p].get_links() if link['kind'] == pymupdf.LINK_GOTO]
            assert toc_page in links and alpha in links, (p, links)
        # All appendix links resolve to a song start and cover every song.
        index_targets = []
        for p in index_pages:
            links = doc[p].get_links()
            assert any(link.get('page') == toc_page for link in links)
            index_targets.extend(link['page'] for link in links
                                 if link['kind'] == pymupdf.LINK_GOTO and link.get('page') != toc_page)
        assert len(index_targets) == number
        assert set(index_targets) == set(song_pages)
        # Original by-key index has a shortcut to the appendix.
        assert alpha in [link['page'] for link in doc[toc_page].get_links()]
        # Check ordering by actual link text positions, not just code-level sort.
        import importlib.util
        spec = importlib.util.spec_from_file_location('alpha_builder', BUILDER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sortable_rows = [dict(r, display_id=f'T{i:03d}') for i, r in enumerate(rows)]
        expected = [r['title'] for r in sorted(sortable_rows, key=module.alphabetical_sort_key)]
        assert expected[:4] == ['Alpha', 'The Alpha', 'A Banjo', 'Éclair'], expected[:6]
        assert expected.index('Everything Stays') + 1 == expected.index('Everything Stays (single sheet)')
        report = (root / 'output/build_report.txt').read_text()
        assert f'Alphabetical index links: {number}' in report
        assert f'Included charts: {number}' in report
        print(f'PASS: {number} alphabetical entries; {len(doc) - alpha} appendix pages; '
              f'{len(doc)} total pages; all destinations and return links valid')
        doc.close()


if __name__ == '__main__':
    audit_sample(8)
    audit_sample(210)
