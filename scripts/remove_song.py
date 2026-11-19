#!/usr/bin/env python3
"""Exclude one arrangement by permanent song_uid without deleting its PDF.

Examples:
  python scripts/remove_song.py --uid S00315 --check
  python scripts/remove_song.py --uid S00315 --apply
"""
import argparse

from song_catalogue import UID_PATTERN, load_catalogue, write_change


def prepare(uid):
    uid = uid.strip()
    if not UID_PATTERN.fullmatch(uid):
        raise ValueError('Specify a permanent UID, e.g. S00315; display IDs are not accepted')
    original, fields, rows = load_catalogue()
    matches = [row for row in rows if row['song_uid'].strip() == uid]
    if len(matches) != 1:
        raise ValueError(f'Expected exactly one {uid} record, found {len(matches)}')
    row = matches[0]
    old_status = (row['status'] or '').strip().lower()
    if old_status == 'exclude':
        raise ValueError(f'{uid} is already excluded')
    if old_status != 'include':
        raise ValueError(f'{uid} status is {old_status!r}, not include; no changes made')
    before_entry = dict(row)
    row['status'] = 'exclude'
    return original, fields, rows, before_entry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uid', required=True, help='Permanent song_uid, e.g. S00315')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true', help='Preview; never write')
    mode.add_argument('--apply', action='store_true', help='Explicitly exclude the arrangement')
    args = parser.parse_args()
    try:
        original, fields, rows, entry = prepare(args.uid)
    except Exception as exc:
        parser.error(f'Validation failed; no changes made: {exc}')
    print('REMOVE SONG - ' + ('CHECK ONLY' if args.check else 'APPLY'))
    print(f"Permanent UID: {entry['song_uid']}  |  {entry['title']}")
    print(f"Key: {entry['key']}  |  current status: {entry['status']} -> exclude")
    print(f"Source PDF: {entry['source_pdf'] or '(none)'}")
    print('Catalogue record and local source PDF will be preserved.')
    if args.check:
        print('PREVIEW ONLY: no files changed.')
        return
    try:
        backup, audit = write_change('remove_song', original, fields, rows,
                                      {'song_uid': entry['song_uid'], 'title': entry['title'],
                                       'key': entry['key'], 'source_pdf': entry['source_pdf'],
                                       'old_status': entry['status'], 'new_status': 'exclude'})
    except Exception as exc:
        parser.error(f'Apply failed: {exc}')
    print('APPLIED: status set to exclude; chart remains on disk.')
    print('Backup:', backup)
    print('Audit:', audit)
    print('Next: python scripts/build_songbook.py')


if __name__ == '__main__':
    main()
