"""Isolated end-to-end smoke test; never changes the real catalogue.
Run: python scripts/test_new_pdf.py
"""
import csv
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]

def run(*args, cwd):
    result = subprocess.run([sys.executable, *args], cwd=cwd, text=True,
                            capture_output=True, check=True)
    return result.stdout

def make_pdf(path, title):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((80, 120), title, fontsize=18)
    doc.save(path)
    doc.close()

def main():
    with tempfile.TemporaryDirectory(prefix='songbook-new-pdf-test-') as temporary:
        root = Path(temporary)
        (root/'scripts').mkdir()
        (root/'data/metadata').mkdir(parents=True)
        (root/'data/song_sheets').mkdir(parents=True)
        (root/'output').mkdir()
        for name in ('build_songbook.py','sync_catalogue.py'):
            shutil.copy2(ROOT/'scripts'/name, root/'scripts'/name)
        fields = ['song_uid','id','key','position','toc_entry','title','artist','status',
                  'source_pdf','key_source','capo_fret','chord_shapes_key']
        rows = [dict.fromkeys(fields,'') for _ in range(2)]
        rows[0].update(song_uid='S00001',id='G001',key='G',position='1',
                       toc_entry='Existing Song',title='Existing Song',status='include',
                       source_pdf='Existing Song.pdf',key_source='reviewed')
        rows[1].update(song_uid='S00002',id='U001',key='Unknown',position='1',
                       toc_entry='Held Variation',title='Held Variation',status='review',
                       source_pdf='Held Variation.pdf',key_source='unknown')
        with (root/'data/metadata/songs.csv').open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
        make_pdf(root/'data/song_sheets/Existing Song.pdf','EXISTING-CHART-TEST')
        make_pdf(root/'data/song_sheets/Held Variation.pdf','HELD-CHART-TEST')
        # This file is completely new to the catalogue.
        make_pdf(root/'data/song_sheets/Brand New Test Song.pdf','NEW-CHART-TEST')
        preview = run('scripts/sync_catalogue.py',cwd=root)
        assert 'New catalogue entries: 1' in preview, preview
        assert len(list(csv.DictReader((root/'data/metadata/songs.csv').open()))) == 2
        applied = run('scripts/sync_catalogue.py','--apply',cwd=root)
        assert 'Catalogue updated:' in applied, applied
        records=list(csv.DictReader((root/'data/metadata/songs.csv').open()))
        assert len(records)==3
        new=[r for r in records if r['source_pdf']=='Brand New Test Song.pdf']
        assert len(new)==1 and new[0]['song_uid']=='S00003', new
        assert new[0]['status'] in ('include','review'), new
        built = run('scripts/build_songbook.py',cwd=root)
        doc=pymupdf.open(root/'output/songbook.pdf')
        all_text='\n'.join(page.get_text() for page in doc)
        for marker in ('EXISTING-CHART-TEST','HELD-CHART-TEST','NEW-CHART-TEST'):
            assert marker in all_text, (marker,built)
        assert len(doc.get_toc())>=5
        assert 'Unrepresented individual PDFs: 0' in (root/'output/build_report.txt').read_text()
        doc.close()
        print('PASS: preview makes no changes')
        print('PASS: new PDF assigned permanent ID S00003')
        print('PASS: existing chart, held chart, and new chart appear in the generated book')
        print('PASS: unrepresented individual PDFs = 0')
        print('PASS: original project files untouched (test runs in a temporary directory)')

if __name__=='__main__':
    main()
