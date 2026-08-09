# Reviewed parent metadata repair contract

`ZoteroReviewedParentMetadataRepair/v2` is a non-executable handoff from
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

Version 2 additionally binds a hash-only `serializer_guard` using the explicit
`ZoteroMetadataCanonicalProjection/v1` contract. Local API and plugin objects
are first mapped to one fixed parent/note/attachment field set with explicit
missing/null defaults and canonical creator, tag, relation, and collection
shapes; unknown fields fail closed. The parent guard keeps the canonical
raw-order hash, a stable hash of every field except the writable profile,
version/dateModified, tags, and collections, plus raw-order and set-normalized
hashes for tags and collections. Each note binds its complete canonical record
and exact content hash. Each attachment binds its canonical raw record, a
stable projection with only `version` and `filename` removed, its local file
SHA-256, size, byte-derived MD5, and hashes of filename and storage path.
Attachment title, URL, link mode, content type, MD5, bytes, key/type, note
content, and tag or collection membership therefore remain fail-closed.
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

The compiler emits `ZoteroParentMetadataRepairTransaction/v2`, containing
one parent and literal operation `ensure_parent_journal_metadata_v1`. It cannot
be mixed with `ZoteroDeclarativeTransaction/v1` operations. Live compilation,
preview, apply, and readback each fail on target, version, content, child, PDF,
membership, or duplicate drift.

For v2 compilation and readback-only recovery, attachment bytes are observed
only by requesting the exact attachment's Local API `/file` endpoint and
following its returned local-file identity under
`$HOME/Zotero/storage/<attachment-key>/`. The compiler opens a direct regular
non-symlink file with no-follow semantics and computes SHA-256 and MD5 from the
bytes it actually reads. The plugin independently computes MD5 from the live
attachment because default `item.toJSON()` omits the Local API's synchronized
`md5` and `mtime` fields. `mtime` is not an identity signal; exact bytes and
size remain authoritative. Expected values are never substituted for an
unavailable observation; redirect, path, identity, read-time size, magic, or
hash drift fails closed without exposing the path in the executable manifest
or public error.

Preview and repeated in-transaction preflight are always strict. Only
post-commit inspection and readback may accept identical tag/collection members
in a different order and same-key attachments whose only raw changes are an
advanced version plus Zotero-managed filename/storage path. The result reports
`content_match=zotero_managed_attachment_rename_and_set_order_equivalent` and
retains expected/observed raw hashes. Version 1 remains supported with its
published exact-only behavior. Every satisfied v2 post/readback state also
requires the observed parent version to be at least the reviewed precondition;
a version rollback fails even when content otherwise matches. A v2
`execution_intent=readback_only`
transaction is rejected by preview and apply in both client and plugin.
