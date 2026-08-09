# Reviewed parent metadata repair contract

`ZoteroReviewedParentMetadataRepair/v1` is a non-executable handoff from
bibliographic review to the constrained local bridge.

## Authority

- The review skill owns source identity, field evidence, transition policy,
  duplicate review, and the sealed source.
- The bridge owns live target binding, authenticated preview, atomic execution,
  and readback.
- Neither layer may merge duplicates, create a parent, edit SQLite, or expose a
  generic field setter.

## Fixed profile

`journal_article_core_v1` contains exactly:

```text
DOI, creators, publicationTitle, volume, issue, pages, date
```

`title`, `shortTitle`, `itemType`, collection membership, children, notes, and
attachments are immutable preconditions. Creators are ordered person authors
with exact `creatorType`, `firstName`, and `lastName` fields.

## Evidence and transitions

Every changed field names one or more sealed evidence artifacts. A changed DOI
requires at least two artifacts, including a verified PDF and publisher or DOI
registry metadata. A non-empty date replacement also requires two artifacts.
Creators and journal citation fields may only be filled from empty values in
v1. Values cannot be cleared.

The reviewed source binds the complete expected and desired profiles, exact
parent version and protected identity, complete child inventory and content
hashes, one evidence PDF hash, exact target, empty full-library duplicate
candidate sets, and canonical JSON hashes for every nested state object.
An exact normalized title/year is a candidate when creator surnames overlap or
either side lacks creators. A differing normalized title/year is a candidate
only when one title is a prefix of the other for at least 20 characters and
both creator sets are non-empty with an overlapping surname.

The draft and reviewed source contain an exact-key, hash-only
`source_evidence_sidecar_ref`: the recognized sidecar schema, exact file
SHA-256, and canonical content SHA-256. The builder must read the explicit
regular `0600` sidecar, verify both digests, and copy only this reference. No
sidecar path enters the reviewed digest or executable transaction.

## Execution boundary

The compiler emits only `ZoteroParentMetadataRepairTransaction/v1`, containing
one parent and literal operation `ensure_parent_journal_metadata_v1`. It cannot
be mixed with `ZoteroDeclarativeTransaction/v1` operations. Live compilation,
preview, apply, and readback each fail on target, version, content, child, PDF,
membership, or duplicate drift.
