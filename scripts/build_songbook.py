"""Build a navigable PDF songbook from data/metadata/songs.csv.

Usage (from repository root): python scripts/build_songbook.py
This never modifies PDFs or the catalogue.
"""
import csv
import re
import unicodedata
from collections import Counter
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / 'data' / 'metadata' / 'songs.csv'
SHEETS = ROOT / 'data' / 'song_sheets'
OUTPUT = ROOT / 'output' / 'songbook.pdf'
REPORT = ROOT / 'output' / 'build_report.txt'

PAGE = pymupdf.Rect(0, 0, 612, 792)  # US Letter
LEFT, RIGHT = 44, 568
TOP, BOTTOM = 86, 732
BODY = pymupdf.Rect(30, 88, 582, 731)
INK = (0.12, 0.16, 0.22)
MUTED = (0.40, 0.45, 0.50)
LINK = (0.10, 0.31, 0.56)

# Index/compilation PDFs are not individual song sheets.
NON_SONG_PDFS = {'Key for keys.pdf', 'Music - ALL.pdf'}
SUPPLEMENT_KEY = 'Unreviewed PDFs'

# Conservative source-page inspection. Blank means effectively no visible ink,
# not merely a short continuation. All-originally-blank documents retain one page.
BLANK_INK_FRACTION = 0.0
SPARSE_INK_FRACTION = 0.006


def source_page_ink_fraction(page):
    """Sample complete source page at low resolution, including raster artwork."""
    pix = page.get_pixmap(matrix=pymupdf.Matrix(0.7, 0.7),
                          colorspace=pymupdf.csGRAY, alpha=False)
    samples = pix.samples
    return sum(v < 245 for v in samples) / max(1, len(samples))


def inspect_source_pages(source, name, report):
    """Return source indexes to print, keeping uncertain/sparse content."""
    ratios = [source_page_ink_fraction(source[i]) for i in range(source.page_count)]
    keep = [i for i, ratio in enumerate(ratios) if ratio > BLANK_INK_FRACTION]
    if not keep:
        report.append(f'CHECK (all source pages appear blank; retained): {name}')
        keep = list(range(source.page_count))
    else:
        for i, ratio in enumerate(ratios):
            if i not in keep:
                report.append(f'SKIPPED blank source page: {name} | source page {i + 1} '
                              f'| dark pixel fraction {ratio:.5%}')
    for i in keep:
        if ratios[i] < SPARSE_INK_FRACTION:
            report.append(f'REVIEW sparse source page (kept): {name} | source page {i + 1} '
                          f'| dark pixel fraction {ratios[i]:.3%}')
    return keep



def printable(value):
    """Make text safe for built-in PDF fonts without affecting source charts."""
    replacements = {'’': "'", '‘': "'", '“': '"', '”': '"',
                    '–': '-', '—': '-', '…': '...', '\u00a0': ' '}
    value = ''.join(replacements.get(c, c) for c in str(value))
    value = unicodedata.normalize('NFKD', value)
    return value.encode('latin-1', 'replace').decode('latin-1')


def trim(text, max_width, size=11, font='helv'):
    text = printable(text)
    if pymupdf.get_text_length(text, fontname=font, fontsize=size) <= max_width:
        return text
    while text and pymupdf.get_text_length(text + '...', fontname=font, fontsize=size) > max_width:
        text = text[:-1]
    return text.rstrip() + '...'


def heading(page, label, title=None):
    page.draw_line((LEFT, 69), (RIGHT, 69), color=(0.75, 0.78, 0.81), width=.7)
    page.insert_text((LEFT, 53), printable(label), fontname='hebo', fontsize=13, color=INK)
    if title:
        page.insert_text((RIGHT, 52), trim(title, 270, 10), fontsize=10,
                         color=MUTED, morph=None, rotate=0)


def footer(page, index, toc=False):
    page.draw_line((LEFT, 748), (RIGHT, 748), color=(0.75, 0.78, 0.81), width=.7)
    page.insert_text((LEFT, 765), f'Page {index + 1}', fontsize=9, color=MUTED)
    if not toc:
        label = 'Back to Table of Contents'
        width = pymupdf.get_text_length(label, fontsize=9)
        x = RIGHT - width
        page.insert_text((x, 765), label, fontsize=9, color=LINK)
        page.insert_link({'kind': pymupdf.LINK_GOTO, 'from': pymupdf.Rect(x - 3, 749, RIGHT + 2, 775), 'page': 0, 'to': pymupdf.Point(0, 0)})


def load_entries():
    with CATALOGUE.open(newline='', encoding='utf-8-sig') as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        required = {'song_uid', 'key', 'title', 'status', 'source_pdf'}
        if not required.issubset(columns):
            raise ValueError(f'Missing catalogue columns: {sorted(required - columns)}')
        rows = list(reader)
    uids = [(r.get('song_uid') or '').strip() for r in rows]
    if any(not re.fullmatch(r'S\d{5,}', uid) for uid in uids) or len(uids) != len(set(uids)):
        raise ValueError('song_uid must be present and unique for every catalogue record')

    keys = []
    selected = []
    warnings = []
    used = Counter()
    for n, row in enumerate(rows, 2):
        status = (row.get('status') or '').strip().lower()
        key = (row.get('key') or '').strip()
        key = key if key and key.upper() not in ('U', 'UNKNOWN', '?', 'NONE') else 'Unknown'
        title = (row.get('title') or row.get('toc_entry') or '').strip()
        filename = (row.get('source_pdf') or '').strip()
        ident = (row.get('id') or f'row {n}').strip()
        uid = row['song_uid'].strip()
        if status not in ('include', 'placeholder', 'review', 'exclude'):
            warnings.append(f'{ident}: unrecognized status {status!r}; omitted')
            continue
        if status in ('review', 'exclude'):
            if status == 'review':
                warnings.append(f'{ident}: awaiting review - {title}')
            continue
        if not title:
            warnings.append(f'{ident}: missing title; omitted')
            continue
        if key != 'Unknown' and not re.fullmatch(r'[A-Ga-g](?:#|b)?(?:m|min)?', key):
            warnings.append(f'{ident}: nonstandard key {key!r}; retained as section label')
        if key not in keys:
            keys.append(key)
        capo = (row.get('capo_fret') or '').strip()
        shapes = (row.get('chord_shapes_key') or '').strip()
        if capo or shapes:
            if not (capo.isdigit() and 0 <= int(capo) <= 12 and
                    re.fullmatch(r'[A-G](?:#|b)?m?', shapes)):
                warnings.append(f'{ident}: invalid capo/chord-shape metadata; note omitted')
                capo, shapes = '', ''
        item = {'title': title, 'key': key, 'file': filename, 'song_uid': uid, 'source_id': ident,
                'status': status, 'row_index': n, 'position': row.get('position', ''),
                'capo_fret': capo, 'chord_shapes_key': shapes}
        if status == 'include':
            if not filename:
                item['status'] = 'placeholder'
                warnings.append(f'{ident}: included song lacks source_pdf; blank page created')
            elif Path(filename).name != filename or filename in ('.', '..'):
                item['status'] = 'placeholder'
                warnings.append(f'{ident}: unsafe PDF filename {filename!r}; blank page created')
            elif not (SHEETS / filename).is_file():
                item['status'] = 'placeholder'
                warnings.append(f'{ident}: missing PDF {filename!r}; blank page created')
            else:
                try:
                    with pymupdf.open(SHEETS / filename) as test:
                        if not test.page_count:
                            raise ValueError('zero pages')
                        item['page_count'] = test.page_count
                    used[filename] += 1
                except Exception as exc:
                    item['status'] = 'placeholder'
                    warnings.append(f'{ident}: unreadable PDF {filename!r} ({exc}); blank page created')
        selected.append(item)

    # Show every individual source PDF exactly once, even when its catalogue
    # record is held for review or excluded as a redundant imported entry.
    # These copies are visibly identified as UNREVIEWED: no musical key is inferred.
    included_files = {item['file'] for item in selected if item['status'] == 'include'}
    supplemental = []
    for path in sorted(SHEETS.iterdir(), key=lambda p: p.name.casefold()):
        if not path.is_file() or path.suffix.lower() != '.pdf':
            continue
        if path.name in NON_SONG_PDFS or path.name in included_files:
            continue
        try:
            with pymupdf.open(path) as source:
                count = source.page_count
                if not count:
                    raise ValueError('zero pages')
        except Exception as exc:
            warnings.append(f'Unreviewed PDF not printable: {path.name} ({exc})')
            continue
        title = path.stem.replace('_', ' ').strip() or path.stem
        supplemental.append({
            'title': title, 'key': SUPPLEMENT_KEY, 'file': path.name,
            'song_uid': '', 'source_id': '', 'status': 'include',
            'row_index': len(rows) + len(supplemental) + 2,
            'position': str(len(supplemental) + 1),
            'capo_fret': '', 'chord_shapes_key': '',
            'page_count': count, 'is_supplemental': True,
        })
    if supplemental:
        selected.extend(supplemental)
        keys.append(SUPPLEMENT_KEY)

    # Display IDs are generated from the selected songs, never from legacy IDs.
    # Preserve existing key order, but always send Unknown to the end.
    keys = ([key for key in keys if key not in ('Unknown', SUPPLEMENT_KEY)]
            + (['Unknown'] if 'Unknown' in keys else [])
            + ([SUPPLEMENT_KEY] if SUPPLEMENT_KEY in keys else []))
    groups = {key: [] for key in keys}
    for item in selected:
        groups[item['key']].append(item)
    for key, group in groups.items():
        # Positions established by the original TOC remain in order; newly
        # appended records follow them in their CSV order.
        def order(item):
            try:
                return (int(item['position']), item['row_index'])
            except (ValueError, TypeError):
                return (10**9, item['row_index'])
        group.sort(key=order)
        for number, item in enumerate(group, 1):
            prefix = 'R' if key == SUPPLEMENT_KEY else ('U' if key == 'Unknown' else key)
            item['display_id'] = f'{prefix}{number:03d}'
    for filename, count in used.items():
        if count > 1:
            warnings.append(f'PDF used {count} times: {filename}')
    return keys, groups, warnings, len(rows)


def plan_toc(keys, groups):
    """Determine TOC pagination before attaching chart pages."""
    planned = [[]]
    y = 108
    for key in keys:
        required = 28 + 19  # heading + first song
        if y + required > 720:
            planned.append([])
            y = 108
        planned[-1].append(('key', key, y))
        y += 28
        for song in groups[key]:
            if y + 19 > 720:
                planned.append([])
                y = 108
            planned[-1].append(('song', song, y))
            y += 19
        y += 7
    return planned


def build():
    keys, groups, warnings, total = load_entries()
    toc_pages = plan_toc(keys, groups)
    doc = pymupdf.open()
    pending_links = []
    page_audit = []
    for toc_idx, rows in enumerate(toc_pages):
        page = doc.new_page(width=PAGE.width, height=PAGE.height)
        heading(page, 'SONGBOOK - CONTENTS')
        if toc_idx == 0:
            page.insert_text((LEFT, 94), 'Click a song to jump to its chart', fontsize=9, color=MUTED)
        for kind, object_, y in rows:
            if kind == 'key':
                page.insert_text((LEFT, y), printable(object_ if object_ == SUPPLEMENT_KEY else f'KEY: {object_}'), fontname='hebo', fontsize=12, color=INK)
            else:
                item = object_
                label = f"{item['display_id']}   {item['title']}"
                page.insert_text((LEFT + 12, y), trim(label, 430, 10.5), fontsize=10.5, color=LINK)
                pending_links.append((toc_idx, pymupdf.Rect(LEFT + 8, y-13, RIGHT, y+5), item))
        footer(page, toc_idx, toc=True)

    outline = [[1, 'Table of Contents', 1]]
    for key in keys:
        group = groups[key]
        outline.append([1, 'Unreviewed PDFs' if key == SUPPLEMENT_KEY else ('Unknown Key' if key == 'Unknown' else f'Key of {key}'), len(doc) + 1])
        for item in group:
            item['page'] = len(doc)
            count = item.get('page_count', 1) if item['status'] == 'include' else 1
            # Open each source ONCE per song, not once per page.
            # Opening from bytes also prevents grafted PDF references from
            # keeping file descriptors alive across a long build.
            if item['status'] == 'include':
                source_data = (SHEETS / item['file']).read_bytes()
                source = pymupdf.open(stream=source_data, filetype='pdf')
            else:
                source = None
            try:
                if source is not None:
                    source_pages = inspect_source_pages(source, item['file'], page_audit)
                else:
                    source_pages = [0]
                for source_page in source_pages:
                    page = doc.new_page(width=PAGE.width, height=PAGE.height)
                    header_left = (f"{item['display_id']}    UNREVIEWED ARRANGEMENT"
                                   if item.get('is_supplemental') else
                                   f"{item['display_id']}    KEY: {key}")
                    if item['capo_fret'] and item['chord_shapes_key']:
                        header_left += (f"    |    {item['chord_shapes_key']} shapes, "
                                        f"Capo {item['capo_fret']}")
                    heading(page, header_left)
                    page.insert_text((LEFT, 81), trim(item['title'], RIGHT-LEFT, 9), fontsize=9, color=MUTED)
                    if source is not None:
                        page.show_pdf_page(BODY, source, source_page, keep_proportion=True)
                    else:
                        page.insert_text((LEFT, 180), trim(item['title'], 510, 19, 'hebo'),
                                         fontname='hebo', fontsize=19, color=INK)
                        page.insert_text((LEFT, 220), 'Chart not yet available', fontsize=12, color=MUTED)
                    footer(page, len(doc)-1)
            finally:
                if source is not None:
                    source.close()
                    del source_data
            outline.append([2, printable(f"{item['display_id']}  {item['title']}"), item['page'] + 1])
    for toc_index, rectangle, item in pending_links:
        doc[toc_index].insert_link({'kind': pymupdf.LINK_GOTO, 'from': rectangle,
                                    'page': item['page'], 'to': pymupdf.Point(0, 0)})
    doc.set_toc(outline)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT.with_name('_songbook_building.pdf')
    try:
        doc.save(tmp, garbage=3, deflate=True)
        tmp.replace(OUTPUT)
    finally:
        doc.close()
        if tmp.exists():
            tmp.unlink()
    all_items = [s for g in groups.values() for s in g]
    supplemental_count = sum(bool(s.get('is_supplemental')) for s in all_items)
    included = sum(s['status'] == 'include' for s in all_items)
    curated_count = included - supplemental_count
    blanks = sum(s['status'] == 'placeholder' for g in groups.values() for s in g)
    unlisted = sorted(p.name for p in SHEETS.glob('*.pdf') if p.name not in {
        s['file'] for g in groups.values() for s in g if s['status'] == 'include'})
    lines = [
        'SONGBOOK BUILD REPORT', '=====================',
        f'Catalogue entries: {total}',
        f'Included charts: {included}',
        f'Placeholder songs: {blanks}',
        f'Review/excluded catalogue entries: {total-curated_count-blanks}',
        f'Curated charts: {curated_count}',
        f'Unreviewed PDFs included: {supplemental_count}',
        f'TOC pages: {len(toc_pages)}',
        f'PDF pages: {sum(1 for _ in pymupdf.open(OUTPUT))}',
        f'Unrepresented individual PDFs: {len([f for f in unlisted if f not in NON_SONG_PDFS])}',
        f'Excluded compilation/index PDFs: {len([f for f in NON_SONG_PDFS if (SHEETS / f).is_file()])}',
        f'Skipped blank source pages: {sum(s.startswith("SKIPPED") for s in page_audit)}',
        f'Sparse source pages kept for review: {sum(s.startswith("REVIEW sparse") for s in page_audit)}',
        '', 'PAGE LAYOUT AUDIT', '-----------------', *(page_audit or ['None']),
        '', 'WARNINGS', '--------', *(warnings or ['None']),
        '', 'UNASSIGNED SOURCE PDFs', '----------------------', *(unlisted or ['None']),
    ]
    REPORT.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines[:13]))
    print(f'Songbook: {OUTPUT}')
    print(f'Report: {REPORT}')


if __name__ == '__main__':
    build()
