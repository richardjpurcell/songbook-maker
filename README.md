# Songbook Maker

Builds a clickable PDF songbook from your own song-sheet PDFs. The book is organized by musical key and includes a key-based table of contents, a clickable alphabetical appendix, bookmarks, page numbers, and links back to both indexes. Sheets without a verified key can appear under **Unknown**. PDFs awaiting review appear in **Unreviewed PDFs**, so every individual song sheet remains accessible without assigning it an unverified key.

## Set up

On macOS, in Terminal:

```bash
cd ~/Projects/songbook_maker
conda activate songbook-maker
```

Requires Python 3 and PyMuPDF (`python -m pip install pymupdf` if needed). The working environment already contains these dependencies.

## Build the songbook

```bash
python scripts/build_songbook.py
open output/songbook.pdf
```

The alphabetical appendix is generated automatically from the same catalogue. Sorting ignores leading **A**, **An**, and **The** without changing the displayed titles. Each chart has return links to both the key contents and alphabetical appendix. The report is `output/build_report.txt`. It shows curated charts, additional unreviewed PDFs, and any individual song files that could not be included. It also lists completely blank source pages skipped during assembly and short/sparse pages retained for manual review. The build also reports any conservatively enlarged source pages. Short continuation pages (less than 38% vertical ink coverage) are not enlarged, even if their text density is above the sparse-page threshold. Original source PDFs are never changed. The index/compilation files `Key for keys.pdf` and `Music - ALL.pdf` are intentionally excluded.

## Add a PDF

1. Copy the new song sheet into `data/song_sheets/`. Use a descriptive filename, such as `My New Song.pdf` or `My New Song in D.pdf`.
2. Preview the catalogue import:

   ```bash
   python scripts/sync_catalogue.py
   ```

3. If the preview looks right, apply it and rebuild:

   ```bash
   python scripts/sync_catalogue.py --apply
   python scripts/build_songbook.py
   open output/songbook.pdf
   ```

The sync assigns a permanent song ID. New, clearly distinct filenames are typically included automatically; possible duplicates are flagged for review. Filename key hints are **not** musical verification. Unreviewed sheets are still accessible in the finished book.

To correct a song's title, key, capo, or inclusion status, edit its row in `data/metadata/songs.csv` carefully. Keep `song_uid` unchanged; `status=include` selects a curated chart, `status=review` leaves it in the unreviewed section, and `status=exclude` prevents its catalogue row from becoming a curated entry (its PDF may still appear once in Unreviewed PDFs). Rebuild after any edit.

## Test chart scaling

```bash
python scripts/test_scaling.py
```

This uses generated sample charts, leaving your song PDFs untouched. The build report lists each page enlarged and the zoom factor. Check those pages visually after a full rebuild.

## Test the add-new-PDF workflow

```bash
python scripts/test_new_pdf.py
```

The test creates a new example PDF in a **temporary copy** of the project, previews and applies the catalogue sync, builds a test songbook, and confirms the new and existing sheets are present. It never adds the example song to your real catalogue.

## Privacy and GitHub

Only commit code, README, and catalogue metadata. Do **not** commit private source song sheets, the original TOC PDF, or generated songbook PDFs. Verify the ignore rules before pushing.

## Test the alphabetical index

```bash
python scripts/test_alphabetical_index.py
```

The test creates its own temporary miniature catalogue and PDF source sheets, builds a book, and checks alphabetical order, link destinations, and the chart return navigation without touching your private song sheets.
