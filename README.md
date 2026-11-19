# Songbook Maker

Builds a private, navigable PDF songbook from locally stored song sheets. The generated book contains a title page, a concise usage guide, a key-based table of contents, printable chart pages, and a clickable alphabetical appendix. Each chart page links back to **both** indexes, and separate arrangements of the same song remain separate entries. Index sorting ignores leading **A**, **An**, or **The** while preserving the displayed title.

## Set up and build

```bash
cd ~/Projects/songbook_maker
conda activate songbook-maker
python scripts/build_songbook.py
open output/songbook.pdf
```

The builder reads `data/metadata/songs.csv`, loads chart PDFs from `data/song_sheets/`, and writes `output/songbook.pdf` and `output/build_report.txt`. It never modifies source song PDFs or the catalogue. PDF bookmarks, chart-page scaling safeguards, blank-page auditing, and both sets of index links are retained. The builder also includes a **180° presentation-only orientation correction** for a known legacy chart; the original source PDF is untouched.

### Key-section ordering

The key-based Table of Contents and the corresponding chart sections follow **alphabetical musical-key order**, with major keys preceding their minor forms when their names share a letter (for example, `A`, `Am`, `B`, `Bm`). Only keys present in the catalogue are displayed. `Unknown` follows the named keys, and an optional `Unreviewed PDFs` section follows `Unknown`. Key ordering does **not** depend on the order of rows in `songs.csv`.

Within each key, charts retain their existing **catalogue `position` order** and display labels are regenerated for that section (such as `E001`, `E002`). Permanent `song_uid` values do not change. The alphabetical song-title appendix still sorts by title, ignoring leading articles. Contents links, appendix links, return links, and PDF bookmarks are rebuilt against the updated page locations, so page numbers may move after this change.

## Add an arrangement

Copy the source PDF into `data/song_sheets/`, preferably using this naming convention:

`Song_Title_Optional_Version_Key.pdf`

For example: `Example_Song_Live_G.pdf`. This is a helpful naming convention, **not** an inference rule: the catalogue controls title, key, permanent UID, and inclusion status. Spaces and apostrophes are allowed in source filenames.

Preview first (use quotes around filenames and titles that contain spaces or apostrophes):

```bash
python scripts/add_song.py --pdf "New_Song_G.pdf" --title "New Song" --key G --check
```

If the preview is correct, explicitly apply the change and rebuild:

```bash
python scripts/add_song.py --pdf "New_Song_G.pdf" --title "New Song" --key G --apply
python scripts/build_songbook.py
open output/songbook.pdf
```

Optional: `--artist "Artist Name"`. Supported key notation includes `G`, `Am`, `Bb`, `F#m`, and the deliberate value `Unknown` when musical evidence is insufficient. The utility checks that the source exists, is a readable nonempty PDF, and is not already registered under any status. It validates existing permanent UIDs and creates the next `S#####` UID. It appends a new `status=include` row without modifying existing records, retaining all existing catalogue columns and choosing the next available position in that key section. Identical titles are allowed for distinct arrangements; the preview warns about them. The legacy `id` field is deliberately left blank because **builder-generated display IDs are not permanent identifiers**.

## Exclude an arrangement without deleting it

Use its **permanent `song_uid`**, not its displayed key/number label:

```bash
python scripts/remove_song.py --uid YOUR_SONG_UID --check
python scripts/remove_song.py --uid YOUR_SONG_UID --apply
python scripts/build_songbook.py
```

Replace `YOUR_SONG_UID` with the actual permanent UID from the catalogue. The preview displays the title, key, current status and original source filename. `--apply` changes **only** that catalogue row's status from `include` to `exclude`; it does **not** delete the row or PDF. Nonexistent IDs, duplicates, already excluded records, and records not currently included are refused. Re-adding a previously excluded song is a separate, deliberate future operation; do not add a second record for its original PDF.

Every successful add/remove operation creates a timestamped original CSV backup under `output/backups/` and a JSON audit under `output/`, including checksums. These files remain local and are ignored by Git. Both operations require an explicit `--check` or `--apply`; no flag means no change.

The builder never puts a PDF associated with **any** `status=exclude` record into the **Unreviewed PDFs** section. A legacy duplicate also has a dedicated regression guard, and excluded source PDFs remain in local storage. A source with an active `include` record remains included even if a separate historical row also references and excludes that filename. Uncatalogued and review-held sources may still appear in Unreviewed PDFs; they are clearly identified, without inferring a musical key.

The existing `scripts/sync_catalogue.py` remains available for broad folder inventory/synchronization. For intentional individual additions, prefer `add_song.py`: it verifies the supplied key and makes the operation explicit.

## Publication title, version and date

Edit `config/songbook.json` to customize the cover title or start a new major version (the title shown here is only an example):

```json
{
  "title": "My Songbook",
  "major_version": 1
}
```

On a first build, the cover shows **Version 1.0** and the local machine's **Last updated** date. The builder records publication metadata in `output/publication_state.json`, which is deliberately **local and not tracked**. Each subsequent successful build compares a SHA-256 fingerprint of the catalogue, the actual included chart PDFs (including any unreviewed charts), the builder script and the optional configuration. If they have not changed, the version and date stay the same. If they change, the minor edition advances (`1.0`, `1.1`, `1.2`, ...), and the date becomes the local date of that successful build. Manually increasing `major_version` starts at `.0` again.

**Keep `output/publication_state.json` in your local backups** along with the catalogue and songbook. If that local file is lost or `output/` is cleared, the next build starts a fresh `1.0` publication sequence; it cannot infer a previous sequential edition from Git or the PDF. Backups/audits and generated PDFs are also local-only.

The two new front-matter pages are included in the PDF page count. The guide page includes a **clickable GitHub repository link** to https://github.com/richardjpurcell/songbook-maker for the source code and documentation. This link does not publish or embed any private chart PDFs. All contents and alphabetical destinations, chart return links and bookmarks are calculated from actual assembled page positions rather than assuming the contents begin at PDF page 1.

## Test without private song PDFs

These commands create synthetic source PDFs in temporary directories and/or exercise pure scaling logic. They never open or modify the private source song sheets:

```bash
python scripts/test_scaling.py
python scripts/test_source_rotation.py
python scripts/test_alphabetical_index.py
python scripts/test_key_order.py
python scripts/test_duplicate_exclusion.py
python scripts/test_new_pdf.py
python scripts/test_catalogue_utilities.py
python scripts/test_front_matter.py
python scripts/test_catalogue_compatibility.py
```

The catalogue compatibility test reads the local catalogue **metadata** but generates replacement synthetic chart PDFs in a temporary directory; it never copies your original source PDFs. `output/build_report.txt` shows curated and unreviewed chart counts, front matter, contents and alphabetical page counts, link counts, skipped blank pages, conservative enlargements, and source-page rotations.

## Privacy and GitHub

The repository ignores `data/song_sheets/*`, `data/table_of_contents/*` and `output/*` (except each `.gitkeep`). **Never commit source PDFs, generated songbooks, private backups, or private audit data.** Only stage code, configuration, documentation and deliberately reviewed catalogue metadata. Verify before any commit:

```bash
git status --short
git ls-files '*.pdf'    # Must print nothing
git diff --cached --name-only
```

If `git ls-files '*.pdf'` prints any filenames, stop and investigate before committing or pushing.
