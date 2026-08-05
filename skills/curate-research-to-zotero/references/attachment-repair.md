# Existing-parent PDF attachment repair

Use this workflow only when a frozen Zotero collection snapshot and a reviewed
acquisition manifest show that an existing parent lacks a readable local PDF.
It is not a parent importer, attachment replacement tool, or metadata editor.

## Contract

`ZoteroAttachmentRepairManifest/v1` is closed and byte-bound. Its target binds
the group ID, Zotero library ID/name, selected local collection ID, collection
key, complete keyed path, and required library/file editability. Its baseline
and acquisition inputs bind absolute paths and SHA-256 hashes. Every entry also
binds the parent key, object version, item type, DOI, title, target membership,
and the complete baseline attachment inventory.

The only entry actions are:

- `attach_missing_pdf`: bind an absolute regular non-symlink file, byte size,
  `%PDF-` magic, SHA-256, content type, and acquisition provenance.
- `metadata_only_skip`: preserve an explicit reason and perform no write.

Unknown fields, duplicate parents, unsupported acquisition states, relative or
symlinked PDFs, input drift, and digest mismatches are rejected. The manifest
digest is the SHA-256 of canonical JSON before the digest field is added.

## Generate and validate

```bash
python scripts/zotero_attachment_repair.py generate \
  /absolute/zotero_baseline.json \
  /absolute/repair_manifest.json \
  /absolute/zotero_attachment_repair_manifest.json \
  --group-id 1234567 \
  --library-id 2 \
  --library-name 'Example Research Library' \
  --local-collection-id 40 \
  --collection-key COLL0001 \
  --collection-path 'Example/Research/DoE'

python scripts/zotero_attachment_repair.py validate \
  /absolute/zotero_attachment_repair_manifest.json
```

Generation and validation recompute every input and PDF hash. Output creation is
exclusive; existing evidence is never overwritten.

## Preview and apply

Prefer the separately reviewed `$zotero-declarative-bridge` plugin instead of
transporting a generated program through Run JavaScript. Compile this exact
manifest without changing its parent, target, attachment, byte, or hash
bindings:

```bash
python ../zotero-declarative-bridge/scripts/zotero_declarative_bridge.py \
  compile-attachment-repair \
  /absolute/zotero_attachment_repair_manifest.json \
  /absolute/zotero_attachment_transaction.json \
  --transaction-id repair-YYYYMMDD
```

Then use its authenticated `probe -> preview -> apply --yes -> readback`
sequence. The plugin supports only fixed declarative operations, keeps the
capability token off HTTP, requires a fresh single-use preview, and repeats
live preflight inside the transaction. Installing the plugin remains a visible,
separately reviewed Zotero Desktop action.

If the bridge is not installed, the generated Desktop runner below remains a
user-operated fallback; do not use blind UI automation to paste or execute it.

Render a preview first. Rendering defaults to preview and refuses a pre-existing
report path.

```bash
python scripts/zotero_attachment_repair.py render \
  /absolute/zotero_attachment_repair_manifest.json \
  --output /absolute/zotero_attachment_repair_preview.js
```

Paste the generated script into Zotero Desktop **Tools -> Developer -> Run
JavaScript**. Preview performs the complete live preflight and writes an
append-only JSON report, but does not mutate Zotero.

Only after reviewing that report, render a separately named apply runner:

```bash
python scripts/zotero_attachment_repair.py render \
  /absolute/zotero_attachment_repair_manifest.json \
  --apply \
  --report /absolute/zotero_attachment_repair_apply_report.json \
  --output /absolute/zotero_attachment_repair_apply.js
```

The Desktop runner requires exact selected-target identity, group/library/file
editability, unchanged parent identity/version/membership, unchanged baseline
attachments, and unchanged source bytes before any write. Preview may inspect a
batch, but fallback apply accepts exactly one parent entry and can import at most
one attachment. It repeats preflight immediately before calling Zotero's public
`Zotero.Attachments.importFromFile()` for that exact parent. It deliberately
does not wrap that API in `Zotero.DB.executeTransaction()`: `importFromFile()`
owns its transaction. The fallback does not delete, rename, relink, or overwrite
existing attachments. Exactly one readable existing PDF with the same hash is
an idempotent no-op; multiple same-hash PDFs or any different readable PDF are
conflicts.

Immediate readback verifies the exact attachment key and parent, content type,
stored size and SHA-256, effective collection inheritance through the exact
parent, absence of direct child collection membership, and a full live inventory
containing exactly one matching readable PDF. If import or readback fails, a
second parent/hash inspection reports `committed` only with that positive
single-attachment evidence; otherwise commit state is `unknown`, never an
assumed rollback. Do not blindly rerun an `unknown` result. The report contains
no PDF content or credentials. Local committed readback is not evidence of
cloud synchronization.
