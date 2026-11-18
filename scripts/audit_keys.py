"""Report possible song-key corrections without changing the catalogue or PDFs.

Run from any directory: python scripts/audit_keys.py
Produces output/key_audit.csv and output/key_audit_summary.txt.
"""
import csv
import re
from collections import Counter
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / 'data' / 'metadata' / 'songs.csv'
SHEETS = ROOT / 'data' / 'song_sheets'
OUT = ROOT / 'output'
KEY_PATTERN = r'[A-G](?:#|b)?(?:m|min)?'
KEY_TOKEN = re.compile(rf'^{KEY_PATTERN}$', re.IGNORECASE)


def canonical(value):
    value = (value or '').strip().replace('♯', '#').replace('♭', 'b')
    if value.lower() in ('', 'u', 'unknown', 'unsorted', 'none'):
        return 'Unknown'
    match = KEY_TOKEN.fullmatch(value)
    if not match:
        return None
    value = match.group(0)
    return value[0].upper() + value[1:].replace('min', 'm').replace('MIN', 'm').lower()


def unique_matches(pattern, text, flags=re.IGNORECASE):
    return list(dict.fromkeys(
        canonical(m.group(1)) for m in re.finditer(pattern, text, flags)
        if canonical(m.group(1)) not in (None, 'Unknown')
    ))


def filename_clues(filename):
    """Conservative patterns: 'in D', 'key of Am', '(G)', or trailing '- C'."""
    stem = Path(filename).stem
    patterns = [
        rf'\b(?:in\s+the\s+key\s+of|in\s+key|key\s*(?:of|:|=)|in)\s+({KEY_PATTERN})(?=$|[\s,;.)-])',
        rf'\(({KEY_PATTERN})\)(?=$|\s)',
        rf'\s[-–—]\s*({KEY_PATTERN})$',
        rf'\s+({KEY_PATTERN})\s*,\s*(?:lyrics|chords)\b',
    ]
    return list(dict.fromkeys(key for p in patterns for key in unique_matches(p, stem)))


def chart_explicit_clues(text):
    """Only explicit declarations near the first page; not chord-progression inference."""
    sample = text[:2500]
    patterns = [
        rf'\bkey\s*(?:of|:|=)\s*({KEY_PATTERN})(?=$|[\s,;.)-])',
        rf'\[\s*in\s+({KEY_PATTERN})\s*\]',
        rf'\(\s*in\s+({KEY_PATTERN})\s*\)',
    ]
    return list(dict.fromkeys(key for p in patterns for key in unique_matches(p, sample)))


def chord_hint(text):
    """Weak evidence only. Count roots on chord-only lines; never auto-assign."""
    scores = Counter()
    # Ignore text-heavy lines, which can contain incidental chord-like words.
    chord = re.compile(r'^[A-G](?:#|b)?(?:m|maj|min|dim|aug|sus)?\d*(?:/[A-G](?:#|b)?)?$', re.I)
    for line in text.splitlines()[:90]:
        tokens = line.strip().replace('|', ' ').replace('[', ' ').replace(']', ' ').split()
        if not 2 <= len(tokens) <= 15:
            continue
        matched = [t.strip(',;:()') for t in tokens]
        if sum(bool(chord.fullmatch(t)) for t in matched) / len(matched) < .85:
            continue
        for token in matched:
            if chord.fullmatch(token):
                root = re.match(r'[A-G](?:#|b)?', token, re.I).group(0)
                scores[root[0].upper() + root[1:]] += 1
    if not scores:
        return ''
    root, n = scores.most_common(1)[0]
    if n < 4 or n / sum(scores.values()) < .40:
        return ''
    return root + ' (chord frequency only; not a verified key)'


def inspect_pdf(filename):
    path = SHEETS / filename
    if not path.is_file():
        return [], '', 'PDF missing'
    try:
        with pymupdf.open(path) as doc:
            if len(doc) == 0:
                return [], '', 'PDF empty'
            # Compilations need special handling; avoid reading hundreds of pages.
            if len(doc) > 20:
                return [], '', f'Long PDF ({len(doc)} pages): inspect manually'
            text = '\n'.join(doc[i].get_text(sort=True) for i in range(min(2, len(doc))))
        return chart_explicit_clues(text), chord_hint(text), ''
    except Exception as exc:
        return [], '', f'PDF unreadable: {type(exc).__name__}: {str(exc)[:120]}'


def audit():
    with CATALOGUE.open(newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        if not {'id', 'key', 'title', 'source_pdf', 'status'}.issubset(reader.fieldnames or []):
            raise ValueError('songs.csv is missing expected columns')

    records = []
    cached = {}
    for song in rows:
        filename = (song.get('source_pdf') or '').strip()
        current_raw = (song.get('key') or '').strip()
        current = canonical(current_raw)
        file_keys = filename_clues(filename) if filename else []
        if filename not in cached and filename:
            cached[filename] = inspect_pdf(filename)
        pdf_keys, chord_evidence, pdf_problem = cached.get(filename, ([], '', ''))
        explicit = sorted(set(file_keys + pdf_keys))
        if current is None:
            verdict = 'INVALID_CATALOGUE_KEY'
        elif len(explicit) > 1:
            verdict = 'CONFLICTING_CLUES'
        elif len(explicit) == 1 and current != 'Unknown' and explicit[0] != current:
            verdict = 'KEY_CONFLICT'
        elif len(explicit) == 1 and current == 'Unknown':
            verdict = 'SUGGEST_KEY'
        elif pdf_problem:
            verdict = 'SOURCE_ISSUE'
        elif not filename:
            verdict = 'NO_PDF_ASSIGNED'
        elif current == 'Unknown':
            verdict = 'UNKNOWN_NEEDS_REVIEW'
        else:
            verdict = 'NO_EXPLICIT_CONFLICT'
        records.append({
            'id': song['id'], 'status': song['status'], 'title': song['title'],
            'current_key': current_raw, 'source_pdf': filename,
            'filename_clue': '; '.join(file_keys),
            'chart_explicit_clue': '; '.join(pdf_keys),
            'chord_hint_unverified': chord_evidence,
            'suggested_key': explicit[0] if len(explicit) == 1 and current == 'Unknown' else '',
            'finding': verdict, 'source_issue': pdf_problem,
        })

    OUT.mkdir(parents=True, exist_ok=True)
    report = OUT / 'key_audit.csv'
    fields = list(records[0]) if records else []
    with report.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    counts = Counter(r['finding'] for r in records)
    lines = ['SONGBOOK KEY AUDIT', '=' * 18, f'Catalogue entries: {len(records)}',
             'No catalogue values or PDFs were modified.', '', 'Findings:']
    lines.extend(f'  {name}: {count}' for name, count in counts.most_common())
    lines.extend(['', 'Priority review (conflicts and suggestions):'])
    priorities = [r for r in records if r['finding'] in ('KEY_CONFLICT', 'CONFLICTING_CLUES', 'SUGGEST_KEY', 'INVALID_CATALOGUE_KEY')]
    lines.extend(f"  {r['id']} | {r['current_key'] or 'Unknown'} | {r['filename_clue'] or r['chart_explicit_clue']} | {r['title']} | {r['finding']}" for r in priorities)
    lines.extend(['', 'Reminder: filename and chord hints are not verified musical keys.',
                  'A capo, transposition, mode, or alternate arrangement may change the intended label.'])
    (OUT / 'key_audit_summary.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines[:9]))
    print(f'\nDetailed CSV: {report}')
    print(f'Summary: {OUT / "key_audit_summary.txt"}')


if __name__ == '__main__':
    audit()
