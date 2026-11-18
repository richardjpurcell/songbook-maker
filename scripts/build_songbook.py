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
# Explicitly retired duplicate: original source remains on disk. Its catalogue
# row must be status=exclude and retain the exact permanent UID and filename.
EXCLUDED_DUPLICATES = {'S00289': 'Stand My Ground.pdf'}
SUPPLEMENT_KEY = 'Unreviewed PDFs'

# Per-source presentation corrections in the assembled book only. Never edit
# the source PDF; use an exact filename and zero-based source-page number.
SOURCE_PAGE_ROTATIONS = {('Red-Winged Blackbird.pdf', 0): 180}


def source_page_rotation(filename, page_index):
    return SOURCE_PAGE_ROTATIONS.get((filename, page_index), 0)


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



# Content-aware enlargement is opt-in for well-separated, compact chart pages.
# Rendered ink bounds include text, scans, drawings and handwritten annotations.
SCALE_SAMPLE = 0.7
SCALE_MARGIN_PT = 22
MIN_SCALE_GAIN = 1.18
MAX_SCALE_GAIN = 1.65
# Continuation pages occupying less than this fraction of page height retain
# their original placement even when the words are not especially sparse.
MIN_CONTINUATION_HEIGHT_FRACTION = 0.38


def choose_source_clip(page, ink_fraction):
    """Return (source crop, gain) only when a safely padded enlargement fits.

    Sparse continuation pages, extremely long/narrow layouts, and pages whose
    ink reaches the edges remain unchanged. Original PDFs are never modified.
    """
    if ink_fraction < 0.003 or (ink_fraction < SPARSE_INK_FRACTION and page.number > 0):
        return None
    # Already-large type does not benefit from enlargement.
    for block in page.get_text('dict').get('blocks', []):
        for line in block.get('lines', []):
            if any(span.get('size', 0) >= 13 for span in line.get('spans', [])):
                return None
    pix = page.get_pixmap(matrix=pymupdf.Matrix(SCALE_SAMPLE, SCALE_SAMPLE),
                          colorspace=pymupdf.csGRAY, alpha=False)
    width, height = pix.width, pix.height
    data = pix.samples
    left, top, right, bottom = width, height, -1, -1
    for y in range(height):
        row = data[y * pix.stride:y * pix.stride + width]
        # Threshold deliberately includes pale writing and scanned pencil marks.
        dark = [i for i, pixel in enumerate(row) if pixel < 245]
        if dark:
            left = min(left, dark[0])
            right = max(right, dark[-1])
            top = min(top, y)
            bottom = y
    if right < left:
        return None
    # A short final verse may have enough dark pixels to pass the sparse-ink
    # threshold, yet scaling it to fill the page makes it visually jarring.
    # Check the vertical ink extent on subsequent pages, independent of density.
    ink_height_fraction = (bottom - top + 1) / height
    if page.number > 0 and ink_height_fraction < MIN_CONTINUATION_HEIGHT_FRACTION:
        return None
    # For safe cropping, do not enlarge any page whose ink touches the edge.
    edge_guard = max(2, round(3 * SCALE_SAMPLE))
    if min(left, top, width - 1 - right, height - 1 - bottom) < edge_guard:
        return None
    source_rect = page.rect
    sx, sy = source_rect.width / width, source_rect.height / height
    clip = pymupdf.Rect(left * sx, top * sy,
                        (right + 1) * sx, (bottom + 1) * sy)
    clip = clip + (-SCALE_MARGIN_PT, -SCALE_MARGIN_PT,
                   SCALE_MARGIN_PT, SCALE_MARGIN_PT)
    clip &= source_rect
    if clip.is_empty or clip.width <= 0 or clip.height <= 0:
        return None
    # Compare fit scales: whole source page versus padded ink bounding box.
    standard = min(BODY.width / source_rect.width, BODY.height / source_rect.height)
    cropped = min(BODY.width / clip.width, BODY.height / clip.height)
    gain = cropped / standard
    if gain < MIN_SCALE_GAIN:
        return None
    if gain > MAX_SCALE_GAIN:
        # Expand crop around the ink, rather than enlarging text excessively.
        factor = gain / MAX_SCALE_GAIN
        middle = (clip.tl + clip.br) / 2
        clip = pymupdf.Rect(middle.x - clip.width * factor / 2,
                            middle.y - clip.height * factor / 2,
                            middle.x + clip.width * factor / 2,
                            middle.y + clip.height * factor / 2)
        # Shift inward instead of slicing the expanded crop at the page edge.
        if clip.x0 < source_rect.x0:
            clip += (source_rect.x0 - clip.x0, 0, source_rect.x0 - clip.x0, 0)
        if clip.x1 > source_rect.x1:
            clip += (source_rect.x1 - clip.x1, 0, source_rect.x1 - clip.x1, 0)
        if clip.y0 < source_rect.y0:
            clip += (0, source_rect.y0 - clip.y0, 0, source_rect.y0 - clip.y0)
        if clip.y1 > source_rect.y1:
            clip += (0, source_rect.y1 - clip.y1, 0, source_rect.y1 - clip.y1)
        if source_rect.contains(clip):
            gain = min(BODY.width / clip.width, BODY.height / clip.height) / standard
        else:
            return None
    return (clip, gain) if gain >= MIN_SCALE_GAIN else None


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


def footer(page, index, toc=False, alphabetical=False):
    page.draw_line((LEFT, 748), (RIGHT, 748), color=(0.75, 0.78, 0.81), width=.7)
    page.insert_text((LEFT, 765), f'Page {index + 1}', fontsize=9, color=MUTED)
    if alphabetical:
        label = 'Back to Key Contents'
        x = RIGHT - pymupdf.get_text_length(label, fontsize=9)
        page.insert_text((x, 765), label, fontsize=9, color=LINK)
        page.insert_link({'kind': pymupdf.LINK_GOTO,
                          'from': pymupdf.Rect(x - 3, 749, RIGHT + 2, 775),
                          'page': 0, 'to': pymupdf.Point(0, 0)})
    elif not toc:
        label = 'Back to Table of Contents'
        width = pymupdf.get_text_length(label, fontsize=9)
        x = RIGHT - width
        page.insert_text((x, 765), label, fontsize=9, color=LINK)
        page.insert_link({'kind': pymupdf.LINK_GOTO, 'from': pymupdf.Rect(x - 3, 749, RIGHT + 2, 775), 'page': 0, 'to': pymupdf.Point(0, 0)})

        # Target is filled in after all charts have been assembled.
        alpha_label = 'Alphabetical Index'
        alpha_x = x - 24 - pymupdf.get_text_length(alpha_label, fontsize=9)
        page.insert_text((alpha_x, 765), alpha_label, fontsize=9, color=LINK)
        return pymupdf.Rect(alpha_x - 3, 749, x - 20, 775)
    return None


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

    # Fail closed if the retired duplicate is renamed, re-included, or absent.
    excluded_duplicate_files = set()
    for uid, expected_pdf in EXCLUDED_DUPLICATES.items():
        matches = [r for r in rows if r['song_uid'].strip() == uid]
        if not matches:
            continue  # Small synthetic fixtures need not contain this catalogue record.
        if len(matches) != 1 or matches[0].get('status', '').strip().lower() != 'exclude' or \
                matches[0].get('source_pdf', '').strip() != expected_pdf:
            raise ValueError(f'Excluded duplicate {uid} must be status=exclude with source {expected_pdf!r}')
        if not (SHEETS / expected_pdf).is_file():
            raise ValueError(f'Excluded duplicate source missing: {expected_pdf}')
        excluded_duplicate_files.add(expected_pdf)

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
        if path.name in NON_SONG_PDFS or path.name in excluded_duplicate_files or path.name in included_files:
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


def alphabetical_sort_key(item):
    # Keep the original title visible, but ignore articles when sorting.
    title = unicodedata.normalize('NFKD', item['title'])
    title = ''.join(ch for ch in title if not unicodedata.combining(ch))
    title = re.sub(r'^(?:a|an|the)\s+', '', title.strip(), flags=re.IGNORECASE)
    title = re.sub(r'^[^\w]+', '', title)
    return (title.casefold(), item['title'].casefold(), item['display_id'])


def plan_alphabetical_index(items):
    # Return index-page rows, using original titles and one entry per chart.
    pages = [[]]
    y = 111
    previous_letter = None
    for item in sorted(items, key=alphabetical_sort_key):
        normalized = alphabetical_sort_key(item)[0]
        letter = normalized[0].upper() if normalized and normalized[0].isalpha() else '#'
        add_letter = letter != previous_letter
        # Do not orphan an alphabet heading at the bottom of a page.
        if y + (24 if add_letter else 0) + 18 > 714:
            pages.append([])
            y = 111
        if add_letter:
            pages[-1].append(('letter', letter, y))
            y += 24
        pages[-1].append(('song', item, y))
        y += 18
        previous_letter = letter
    return pages


def build():
    keys, groups, warnings, total = load_entries()
    toc_pages = plan_toc(keys, groups)
    doc = pymupdf.open()
    pending_links = []
    page_audit = []
    chart_alpha_buttons = []
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
        if toc_idx == 0:
            # A top-page shortcut; its destination is determined after charts.
            jump_text = 'Alphabetical Index'
            jump_x = RIGHT - pymupdf.get_text_length(jump_text, fontsize=9)
            page.insert_text((jump_x, 94), jump_text, fontsize=9, color=LINK)
            pending_links.append((toc_idx, pymupdf.Rect(jump_x - 4, 80, RIGHT + 2, 99), None))

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
                        ink_fraction = source_page_ink_fraction(source[source_page])
                        rotation = source_page_rotation(item['file'], source_page)
                        # Rotation is a presentation correction, not a crop.
                        # Keep the whole scanned sheet to avoid losing marginal notes.
                        choice = (None if rotation else
                                  choose_source_clip(source[source_page], ink_fraction))
                        if rotation:
                            page_audit.append(
                                f'ROTATED source page: {item["file"]} | '
                                f'source page {source_page + 1} | {rotation} degrees')
                        if choice is None:
                            page.show_pdf_page(BODY, source, source_page,
                                               keep_proportion=True, rotate=rotation)
                        else:
                            clip, gain = choice
                            page.show_pdf_page(BODY, source, source_page,
                                               keep_proportion=True, clip=clip, rotate=rotation)
                            page_audit.append(
                                f'ENLARGED source page: {item["file"]} | '
                                f'source page {source_page + 1} | {gain:.2f}x | '
                                f'clip {tuple(round(float(v), 1) for v in clip)}')
                    else:
                        page.insert_text((LEFT, 180), trim(item['title'], 510, 19, 'hebo'),
                                         fontname='hebo', fontsize=19, color=INK)
                        page.insert_text((LEFT, 220), 'Chart not yet available', fontsize=12, color=MUTED)
                    alpha_button = footer(page, len(doc)-1)
                    chart_alpha_buttons.append((len(doc)-1, alpha_button))
            finally:
                if source is not None:
                    source.close()
                    del source_data
            outline.append([2, printable(f"{item['display_id']}  {item['title']}"), item['page'] + 1])
    # Append a separate alphabetically sorted appendix, keeping all chart
    # destinations and the original key-based contents page numbers stable.
    all_items = [item for key in keys for item in groups[key]]
    alpha_start = len(doc)
    alphabetical_pages = plan_alphabetical_index(all_items)
    alpha_links = 0
    for rows in alphabetical_pages:
        index_page_number = len(doc)
        page = doc.new_page(width=PAGE.width, height=PAGE.height)
        heading(page, 'SONGBOOK - ALPHABETICAL INDEX')
        page.insert_text((LEFT, 86), 'Song title', fontsize=9, color=MUTED)
        column_heading = 'Key / ID'
        page.insert_text((RIGHT - pymupdf.get_text_length(column_heading, fontsize=9), 86),
                         column_heading, fontsize=9, color=MUTED)
        for kind, item_or_letter, y in rows:
            if kind == 'letter':
                page.insert_text((LEFT, y), item_or_letter,
                                 fontname='hebo', fontsize=11, color=INK)
                continue
            item = item_or_letter
            # Right-hand key/ID column is aligned to the page margin.
            suffix = f"{item['key']}  |  {item['display_id']}"
            suffix_width = pymupdf.get_text_length(printable(suffix), fontsize=9)
            page.insert_text((RIGHT - suffix_width, y), printable(suffix),
                             fontsize=9, color=MUTED)
            page.insert_text((LEFT + 12, y),
                             trim(item['title'], RIGHT - LEFT - suffix_width - 31, 9.5),
                             fontsize=9.5, color=LINK)
            page.insert_link({'kind': pymupdf.LINK_GOTO,
                              'from': pymupdf.Rect(LEFT + 8, y - 13, RIGHT + 2, y + 4),
                              'page': item['page'], 'to': pymupdf.Point(0, 0)})
            alpha_links += 1
        footer(page, index_page_number, alphabetical=True)
    outline.append([1, 'Alphabetical Index', alpha_start + 1])
    for page_number, rectangle in chart_alpha_buttons:
        doc[page_number].insert_link({'kind': pymupdf.LINK_GOTO,
                                       'from': rectangle, 'page': alpha_start,
                                       'to': pymupdf.Point(0, 0)})
    for toc_index, rectangle, item in pending_links:
        doc[toc_index].insert_link({'kind': pymupdf.LINK_GOTO, 'from': rectangle,
                                    'page': alpha_start if item is None else item['page'],
                                    'to': pymupdf.Point(0, 0)})
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
    unrepresented = [f for f in unlisted if f not in NON_SONG_PDFS and
                     f not in EXCLUDED_DUPLICATES.values()]
    lines = [
        'SONGBOOK BUILD REPORT', '=====================',
        f'Catalogue entries: {total}',
        f'Included charts: {included}',
        f'Placeholder songs: {blanks}',
        f'Review/excluded catalogue entries: {total-curated_count-blanks}',
        f'Curated charts: {curated_count}',
        f'Unreviewed PDFs included: {supplemental_count}',
        f'TOC pages: {len(toc_pages)}',
        f'Alphabetical index pages: {len(alphabetical_pages)}',
        f'Alphabetical index links: {alpha_links}',
        f'PDF pages: {sum(1 for _ in pymupdf.open(OUTPUT))}',
        f'Unrepresented individual PDFs: {len(unrepresented)}',
        f'Excluded duplicate PDFs: {len([f for f in unlisted if f in EXCLUDED_DUPLICATES.values()])}',
        f'Excluded compilation/index PDFs: {len([f for f in NON_SONG_PDFS if (SHEETS / f).is_file()])}',
        f'Skipped blank source pages: {sum(s.startswith("SKIPPED") for s in page_audit)}',
        f'Sparse source pages kept for review: {sum(s.startswith("REVIEW sparse") for s in page_audit)}',
        f'Source pages enlarged: {sum(s.startswith("ENLARGED") for s in page_audit)}',
        f'Source pages rotated: {sum(s.startswith("ROTATED") for s in page_audit)}',
        '', 'PAGE LAYOUT AUDIT', '-----------------', *(page_audit or ['None']),
        '', 'WARNINGS', '--------', *(warnings or ['None']),
        '', 'INTENTIONALLY EXCLUDED DUPLICATE PDFs', '-------------------------------------',
        *(sorted(f for f in unlisted if f in EXCLUDED_DUPLICATES.values()) or ['None']),
        '', 'UNASSIGNED SOURCE PDFs', '----------------------',
        *(sorted(f for f in unlisted if f not in EXCLUDED_DUPLICATES.values()) or ['None']),
    ]
    REPORT.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines[:13]))
    print(f'Songbook: {OUTPUT}')
    print(f'Report: {REPORT}')


if __name__ == '__main__':
    build()
