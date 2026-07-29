# Document manifest

Build this before a complete read or whenever PDF extraction and printed pagination differ.

## Identity and integrity

```text
source_id
canonical_identity
publication/version status
local_path
sha256
file_size
physical_page_count
main_text_range
supplement_range
appendix_range
printed-to-physical page map
text extraction tool/status
render inspection tool/status
```

Use a dual locator for composite files, for example:

```text
main p. 3934 | PDF physical p. 3
SI p. 12 | PDF physical p. 18
```

## Artifact inventory

| Artifact | Printed locator | Physical page | Extraction quality | Render checked | Decision relevance | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Figure 1 | main p. 3934 | 3 | good | yes | central | reconstructed |
| Eq. (10) | SI p. 6 | 12 | broken | yes | central | verified-from-render |

Inventory:

- all figures and tables;
- numbered equations, theorems, algorithms, and code blocks;
- appendices and supplementary sections;
- data/code links and claimed availability.

For each artifact use `not_relevant`, `inspected`, `evidence-extracted`, `reconstructed`, or `unresolved`. “Code available” means the paper reports a link; use `code-retrieved` and `code-executed` only after those actions actually occurred.

## Extraction quality

Check several pages from the beginning, middle, appendix, and supplement. Detect:

- missing glyphs or equations;
- duplicated/reordered hidden text;
- broken columns;
- OCR substitutions;
- captions separated from figures;
- printed page labels that reset in supplements.

When the text layer is unreliable, treat rendered pages as authoritative and mark locators `verified-from-render`. Never repair symbols from context without an inference label.

## Completeness report

At delivery record:

```text
pages inspected / total pages
figures inspected / total figures
tables inspected / total tables
numbered equations or theorems inventoried
supplements inspected
artifacts unresolved and why
references independently followed
```

This is an inspection accounting record, not evidence that every page received equal analytical depth.
