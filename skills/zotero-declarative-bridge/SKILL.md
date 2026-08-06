---
name: zotero-declarative-bridge
description: Resolve an exact collection key read-only or execute reviewed, hash-bound mutations on existing Zotero Desktop parents through a constrained local plugin. Use when a compiler needs Zotero's internal numeric collection ID, or curation must add exact collection membership, update only a reviewed parent shortTitle, create or update one child note, or attach a verified local PDF without SQLite edits, cloud credentials, arbitrary JavaScript, or blind UI automation.
---

# Zotero Declarative Bridge

Keep semantic curation in `$curate-research-to-zotero`. This skill is only the
authenticated exact-key resolver and local transaction executor for an already
reviewed target or manifest.

## Fixed workflow

1. If an authorized group-library ID and collection key are known but Zotero's
   internal collection ID is not, use the read-only `resolve-collection`
   command in [protocol.md](references/protocol.md). Do not enumerate libraries
   or collections to guess either input.
2. Read [protocol.md](references/protocol.md) and compile one of the four
   supported operations with [zotero_declarative_bridge.py](scripts/zotero_declarative_bridge.py).
   For a sealed `ZoteroReviewedMutationBatch/v1`, use
   `compile-reviewed-batch` rather than copying reviewed fields into an ad hoc
   bridge manifest.
3. Validate the sealed manifest. Never add an operation type or dynamic method
   name to bypass the protocol.
4. Build and inspect the XPI with [build_xpi.py](scripts/build_xpi.py). The build
   must bind the external update manifest and final XPI hash. Follow
   [install-uninstall.md](references/install-uninstall.md); prefer Zotero's
   visible Plugins action for the packed XPI. The stable skill does not install
   source proxies or change profile discovery preferences.
5. Before installation, require Zotero's own `loadManifestFromFile` preflight to
   return the expected ID/version with no `additionalErrors`; offline JSON-schema
   checks are not a substitute for this runtime loader gate.
6. Require registry-active ID/version, a private capability file, and an
   authenticated `probe` before `preview`. XPI presence alone proves nothing.
7. Pass the explicit private capability file to `probe`, then run `preview`.
   Review its receipt before `apply --yes`.
8. Run `readback` against the same sealed manifest. A child note is satisfied
   only by an exact raw hash or the strict Zotero storage-equivalence contract
   in [protocol.md](references/protocol.md). Treat partial, unknown, material
   drift, or formula mismatch as failure. Never retry an apply reported as
   `committed_unverified`; quiesce editors and perform a fresh readback.

The bridge is loopback-only and accepts `application/octet-stream` envelopes
authenticated with a nonce and HMAC. The random capability token never crosses
HTTP. It supports only:

- `ensure_collection_membership`
- `ensure_parent_short_title`
- `ensure_child_note`
- `ensure_pdf_attachment`

The separate authenticated `resolve_collection` action is read-only and is not
a transaction operation. It accepts exactly one authorized internal group
library ID plus one exact collection key and returns only that pair plus the
numeric collection ID. Missing, ambiguous, deleted, non-group, or mismatched
lookups fail closed.

A sealed manifest is either a multi-operation `db_atomic` transaction containing
only collection, short-title, and note operations, or an attachment-only plan.
Preview refuses to issue a token when more than one PDF still needs import.
`ensure_pdf_attachment` uses Zotero's own single-file transaction and is never
nested inside the bridge database transaction. Mixed metadata/PDF manifests are
invalid and attachment batches must be compiled one parent at a time.

It never removes data, edits any parent bibliography field other than the
explicitly bound `shortTitle`, evaluates code, reads SQLite, or obtains Zotero
sync credentials. A preview expires and is single-use. A
successful local readback does not prove cloud synchronization.

Bibliographic `shortTitle` remains unchanged by default. Research workflows may
opt into the decision-oriented policy only with a requested language. That
policy requires `适用场景：结论/警示` semantics (or the documented English
equivalent) and rejects a simple truncation of the bibliography title. The
policy is a deterministic structural gate, not a substitute for human review of
the scientific conclusion.

## Literature-note authority

Execute reviewed literature HTML but do not author it. Install
`$curate-research-to-zotero` alongside this skill when compiling reviewed
literature batches; its clean-note validator is the sole content authority.

For a reviewed note update that intentionally preserves an already-correct
short title, pass `--allow-unchanged-short-titles`. Never use it to admit an
all-no-op entry; compilation remains fail closed unless the same entry changes
the note.
