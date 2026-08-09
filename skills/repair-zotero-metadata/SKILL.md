---
name: repair-zotero-metadata
description: Review and stage evidence-bound corrections to bibliographic metadata on an existing Zotero parent. Use when a verified source conflicts with DOI, creators, journal, volume, issue, pages, or date on an existing journalArticle. Not for discovery, new-parent import, duplicate merge, notes, PDFs, collections, shortTitle, or direct Zotero execution.
---

# Repair Zotero Metadata

Keep bibliographic review separate from Zotero execution.

## Fixed workflow

1. Accept an already verified source identity and exact existing-parent snapshot.
2. Read [reviewed-repair-contract.md](references/reviewed-repair-contract.md).
3. Prove field-level identity from a verified PDF plus publisher or DOI-registry
   evidence. Do not discover or download a replacement here.
4. Search the complete target library for desired-DOI and
   title/year/creator duplicates. Stop on every candidate; never merge or create
   a replacement parent.
5. Seal the current read-only live-evidence sidecar with its canonical content
   digest and exact file SHA-256. Build and validate one private
   `ZoteroReviewedParentMetadataRepair/v2` with
   [metadata_repair_contract.py](scripts/metadata_repair_contract.py), passing
   that `0600` sidecar through `--source-evidence-sidecar`.
6. Bind the v2 `serializer_guard` from the exact pre-state through
   `ZoteroMetadataCanonicalProjection/v1`: parent stable non-profile data, raw
   and set-normalized tag/collection hashes, exact note projections, and
   attachment raw/stable/file/path hashes. MD5 must come from the attachment
   bytes rather than serializer presence. A PDF-only check is not sufficient.
7. Route the sealed source to `$zotero-declarative-bridge` command
   `compile-reviewed-metadata-repair`. Preview, explicit apply, and exact
   readback remain bridge responsibilities.

The write profile remains `journal_article_core_v1`. It contains exactly `DOI`,
`creators`, `publicationTitle`, `volume`, `issue`, `pages`, and `date`.
Bibliographic `title` and `shortTitle` are immutable identity preconditions.
Existing non-empty creators or journal citation fields are not overwritten by
v1. DOI and date replacement require two independently bound evidence
artifacts. No value may be cleared.

Reviewed source v1 remains validation-compatible and exact-only. New work uses
v2. A v2 `--readback-only` compilation is allowed only when the live profile is
already desired and the sealed guard proves exact or narrowly bounded
Zotero-managed storage equivalence. Its transaction cannot be previewed or
applied.

Reviewed sources are private operational state. Create them with mode `0600`
outside the public repository. This skill never writes Zotero, reads SQLite,
drives the Zotero UI, or publishes item keys and library identifiers.
