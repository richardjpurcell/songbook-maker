#!/usr/bin/env python3
"""Add a validated local song chart as a new permanent catalogue record.

Examples:
  python scripts/add_song.py --pdf "Song_Name_G.pdf" --title "Song Name" --key G --check
  python scripts/add_song.py --pdf "Song_Name_G.pdf" --title "Song Name" --key G --apply
"""
import argparse

import pymupdf

from song_catalogue import (KEY_PATTERN, SHEETS, checked_pdf_path,
                            load_catalogue, write_change)


def prepare(filename, title, key, artist=''):
    title = title.strip()
    key = key.strip()
    artist = artist.strip()
    if not title or any(c in title for c in '\r\n\x00'):
        raise ValueError('Title must be nonempty and on one line')
    if not key or not (KEY_PATTERN.fullmatch(key) or key == 'Unknown'):
        raise ValueError('Key must be like G, Am, Bb, F#m, or Unknown (case-sensitive)')
    if any(c in artist for c in '\r\n\x00'):
        raise ValueError('Artist must be on one line')
    path = checked_pdf_path(filename)
    try:
        with pymupdf.open(path) as pdf:
            if not pdf.is_pdf or pdf.needs_pass or pdf.page_count < 1:
                raise ValueError('Source PDF is encrypted, invalid, or empty')
            page_count = pdf.page_count
            # Validate that each page can be read without modifying the file.
            for page in pdf:
                _ = page.rect
    except Exception as exc:
        raise ValueError(f'Source PDF is not readable: {exc}') from exc
    original, fields, rows = load_catalogue()
    if any((row['source_pdf'] or '').strip().casefold() == filename.casefold() for row in rows):
        raise ValueError('Source PDF already has a catalogue record (any status)')
    next_number = max(int(row['song_uid'].strip()[1:]) for row in rows) + 1
    uid = f'S{next_number:05d}'
    if any(row['song_uid'] == uid for row in rows):
        raise ValueError('Permanent UID collision')
    positions = []
    for row in rows:
        if (row['key'] or '').strip() == key:
            pos = (row['position'] or '').strip()
            if pos:
                if not pos.isdigit():
                    raise ValueError(f"Non-numeric position for {row['song_uid']}: {pos!r}")
                positions.append(int(pos))
    new = {field: '' for field in fields}
    new.update(song_uid=uid, title=title, key=key, position=str(max(positions, default=0) + 1),
               source_pdf=filename, status='include')
    if 'toc_entry' in fields:
        new['toc_entry'] = title
    if 'artist' in fields:
        new['artist'] = artist
    if 'key_source' in fields:
        new['key_source'] = 'manual_add'
    duplicate_titles = [row['song_uid'] for row in rows
                        if (row['title'] or '').strip().casefold() == title.casefold()]
    rows.append(new)
    return original, fields, rows, new, page_count, duplicate_titles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', required=True, help='Exact filename inside data/song_sheets/')
    parser.add_argument('--title', required=True, help='Chart title shown in the indexes')
    parser.add_argument('--key', required=True, help='Musical key, such as G, Am, F#m, or Unknown')
    parser.add_argument('--artist', default='', help='Optional artist metadata')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true', help='Preview; never write')
    group.add_argument('--apply', action='store_true', help='Explicitly add the catalogue row')
    args = parser.parse_args()
    try:
        before, fields, rows, entry, pages, duplicates = prepare(args.pdf, args.title, args.key, args.artist)
    except Exception as exc:
        parser.error(f'Validation failed; no changes made: {exc}')
    print('ADD SONG - ' + ('CHECK ONLY' if args.check else 'APPLY'))
    print(f"Permanent UID: {entry['song_uid']}  |  {entry['title']}")
    print(f"Key: {entry['key']}  |  section position: {entry['position']}  |  status: include")
    print(f"Local source: {entry['source_pdf']} ({pages} pages)")
    print(f'Catalogue records: {len(rows)-1} -> {len(rows)}')
    if duplicates:
        print('NOTE: Existing arrangement(s) with the same title: ' + ', '.join(duplicates))
        print('Separate arrangements are permitted; confirm the source PDF is distinct.')
    print('Source PDF will not be modified or copied.')
    if args.check:
        print('PREVIEW ONLY: no files changed.')
        return
    try:
        backup, audit = write_change('add_song', before, fields, rows,
                                      {'song': entry, 'source_pdf_pages': pages})
    except Exception as exc:
        parser.error(f'Apply failed: {exc}')
    print('APPLIED: one catalogue record added.')
    print('Backup:', backup)
    print('Audit:', audit)
    print('Next: python scripts/build_songbook.py')


if __name__ == '__main__':
    main()
