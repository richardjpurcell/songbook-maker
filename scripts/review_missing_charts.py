"""Read-only review of catalogue entries lacking assigned PDF charts.

Run: python scripts/review_missing_charts.py
Writes output/missing_chart_review.csv and output/missing_chart_summary.txt.
Never changes songs.csv or source PDFs. Review candidates before approving.
"""
import csv
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / 'data/metadata/songs.csv'
SHEETS = ROOT / 'data/song_sheets'
OUT = ROOT / 'output'


def normalize(value):
    s = unicodedata.normalize('NFKD', str(value or '').casefold())
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.replace('’', "'").replace('&', ' and ')
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', s).split())


def title_variants(text, *, filename=False):
    """Generate conservative variants; retain original to avoid losing title material."""
    s = Path(text).stem if filename else str(text or '')
    variants = {normalize(s)}
    # Remove only plausible terminal musical annotations, not arbitrary title words.
    reduced = re.sub(r'\s+(?:in\s+)?(?:key\s+of\s+)?[A-Ga-g](?:#|b)?m?\s*$', '', s, flags=re.I)
    reduced = re.sub(r'\s*\(\s*(?:in\s+)?[A-Ga-g](?:#|b)?m?\s*\)\s*$', '', reduced, flags=re.I)
    variants.add(normalize(reduced))
    # A trailing parenthetical might be an artist; this is an additional comparison, never replacement.
    no_credit = re.sub(r'\s*\([^()]+\)\s*$', '', reduced)
    variants.add(normalize(no_credit))
    no_credit = re.sub(r'\s*\[[^][]+\]\s*$', '', no_credit)
    variants.add(normalize(no_credit))
    # Filenames commonly end in numbered versions.
    if filename:
        variants.add(normalize(re.sub(r'(?:[- ]+\d+)\s*$', '', no_credit)))
    return {v for v in variants if v}


def compare(left, right):
    return max(SequenceMatcher(None, a, b).ratio() for a in left for b in right)


def classify(score):
    if score >= .985:
        return 'STRONG_TITLE_MATCH_REVIEW'
    if score >= .83:
        return 'POSSIBLE_MATCH_REVIEW'
    if score >= .66:
        return 'WEAK_MATCH_REVIEW'
    return 'NO_PLAUSIBLE_MATCH'


def main():
    with CATALOGUE.open(newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or ())
        required = {'song_uid', 'id', 'key', 'title', 'toc_entry', 'status', 'source_pdf'}
        if not required <= fields:
            raise SystemExit(f'Missing catalogue columns: {sorted(required-fields)}')
        songs = list(reader)
    uids = [s['song_uid'].strip() for s in songs]
    if len(uids) != len(set(uids)) or any(not x for x in uids):
        raise SystemExit('Permanent song IDs missing or duplicated; no review generated.')
    available = sorted((p.name for p in SHEETS.iterdir() if p.is_file() and p.suffix.lower() == '.pdf'), key=str.casefold)
    assigned = {}
    for s in songs:
        name = (s['source_pdf'] or '').strip()
        if name:
            assigned.setdefault(name, []).append(s)
    available_set = set(available)
    unused = [n for n in available if n not in assigned]
    missing = [s for s in songs if not (s['source_pdf'] or '').strip() and s['status'].strip().lower() not in ('exclude',)]
    names = {name: title_variants(name, filename=True) for name in available}
    result = []
    for s in missing:
        titles = title_variants(s['title']) | title_variants(s['toc_entry'])
        matches = sorted(((compare(titles, names[name]), name) for name in available), key=lambda x: (-x[0], x[1].casefold()))[:5]
        # Prefer an available, unassigned PDF if it scores comparably to an assigned one.
        best_unused = sorted(((score, name) for score, name in matches if name not in assigned), reverse=True)
        top_score, top_name = matches[0] if matches else (0., '')
        matches_assigned = assigned.get(top_name, [])
        verdict = classify(top_score)
        if top_name and matches_assigned and top_score >= .66:
            verdict = 'POSSIBLE_DUPLICATE_OR_ALTERNATE'
        elif top_name and top_score >= .66 and len(matches) > 1 and matches[1][0] >= top_score - .04:
            verdict = 'AMBIGUOUS_MULTIPLE_MATCHES'
        result.append({
            'song_uid': s['song_uid'], 'legacy_id': s['id'], 'key': s['key'],
            'title': s['title'] or s['toc_entry'], 'status': s['status'],
            'finding': verdict, 'candidate_1': top_name, 'score_1': f'{top_score:.3f}',
            'candidate_1_assigned_to': '; '.join(f"{x['song_uid']} ({x['id']})" for x in matches_assigned),
            'candidate_2': matches[1][1] if len(matches) > 1 else '',
            'score_2': f'{matches[1][0]:.3f}' if len(matches) > 1 else '',
            'candidate_3': matches[2][1] if len(matches) > 2 else '',
            'score_3': f'{matches[2][0]:.3f}' if len(matches) > 2 else '',
            'best_unassigned_candidate': best_unused[0][1] if best_unused else '',
            'best_unassigned_score': f'{best_unused[0][0]:.3f}' if best_unused else '',
            'decision': '', 'approved_pdf': '',
        })
    OUT.mkdir(parents=True, exist_ok=True)
    csv_path = OUT / 'missing_chart_review.csv'
    if result:
        with csv_path.open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=list(result[0]))
            writer.writeheader()
            writer.writerows(result)
    else:
        csv_path.write_text('song_uid,legacy_id,key,title,status,finding\n', encoding='utf-8')
    counts = Counter(r['finding'] for r in result)
    lines = ['MISSING CHART RECONCILIATION — PREVIEW ONLY', '=' * 43,
             f'Catalogue entries: {len(songs)}', f'Source PDFs: {len(available)}',
             f'Entries without assigned PDFs (excluding excluded): {len(missing)}',
             f'PDF files not referenced by any catalogue row: {len(unused)}', '', 'Findings:']
    lines += [f'  {k}: {v}' for k, v in counts.most_common()]
    lines += ['', 'TOP MATCHES TO REVIEW', '---------------------']
    for r in result:
        if r['finding'] != 'NO_PLAUSIBLE_MATCH':
            lines.append(f"{r['song_uid']} [{r['legacy_id']}] {r['title']} | {r['finding']} | {r['score_1']}: {r['candidate_1']}" + (f" (assigned to {r['candidate_1_assigned_to']})" if r['candidate_1_assigned_to'] else ''))
    lines += ['', 'IMPORTANT', '---------',
              'Matching uses title similarity, not PDF content or musical verification.',
              'Never approve a candidate solely because its score is high.',
              'An assigned candidate may represent a duplicate title, alternate arrangement, or same chart.',
              'All decisions are left blank. No source PDF or catalogue file was changed.',
              f'Detailed CSV: {csv_path}']
    summary = OUT / 'missing_chart_summary.txt'
    summary.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines[:9]))
    print(f'\nDetailed review: {csv_path}')
    print(f'Summary: {summary}')


if __name__ == '__main__':
    main()
