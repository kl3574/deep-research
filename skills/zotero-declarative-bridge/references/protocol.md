# Declarative bridge protocol

## Trust split

`curate-research-to-zotero` owns source identity, note validation, PDF
acquisition, deduplication, target approval, and manifest review. This bridge
owns only a fixed local projection into Zotero Desktop.

Zotero's Local API is read-only in the current client. Connector save routes
create new records and are not a version-guarded existing-item update API. The
official Connector HTTP Server documentation permits a privileged plugin to
register an endpoint and warns that unsafe web content can issue some loopback
requests. The bridge therefore adds a capability and replay-resistant HMAC
layer rather than exposing a generic JavaScript endpoint.

Primary references:

- https://www.zotero.org/support/dev/client_coding/connector_http_server
- https://www.zotero.org/support/dev/client_coding/javascript_api
- https://www.zotero.org/support/dev/zotero_7_for_developers
- https://www.zotero.org/support/dev/web_api/v3/basics

## Security properties

- The plugin registers exactly `/deep-research/transaction/v1` on Zotero's
  existing loopback server. Zotero itself rejects non-loopback Host headers.
- The endpoint accepts only `POST application/octet-stream`. This avoids the
  server's debug logging of JSON/text bodies and blocks browser simple-request
  content types.
- Startup creates a 256-bit random capability token in the Zotero profile with
  mode `0600`. Requests contain a key ID, timestamp, 128-bit nonce, and HMAC;
  the token is never transmitted. Valid nonces cannot be replayed.
- Preview returns a second random, expiring, single-use token bound to the
  manifest digest and complete live-state digest. Apply repeats preflight both
  before and inside the database transaction.
- Request bodies are bounded at 8 MiB, notes at 1 MiB, PDFs at 256 MiB, entries
  at 100, and operations at four per parent.
- Schemas reject unknown fields. Operation names are an enum, not dispatchable
  JavaScript names. No `eval`, `Function`, module path, SQL, delete, or arbitrary
  metadata operation exists. The only parent-field operation is the literal
  `ensure_parent_short_title`; callers cannot supply a field name.

## Stable installation boundary

The stable skill intentionally has no source-proxy installer. It never changes
`extensions.startupScanScopes`, `extensions.autoDisableScopes`,
`extensions.enabledScopes`, `extensions.lastApp*`, `extensions.json`, or the
Zotero profile database. Install the reviewed, hash-bound XPI through Zotero's
visible Plugins action. A source proxy or profile preference edit performed by
separate developer tooling is outside this skill's supported and tested trust
boundary.

## Manifest

`ZoteroDeclarativeTransaction/v1` binds:

- exact local library ID, library type/type ID/name, editability;
- exact collection ID/key and every keyed path component;
- exact parent key, version, type, title, normalized DOI, target membership,
  and SHA-256 of that identity object;
- complete child-note or attachment baselines for the operation that needs it;
- exact old/new note hashes or local PDF path/size/magic/hash;
- for `shortTitle`, redundant exact library ID, parent key/version, expected old
  value, and non-empty reviewed new value;
- SHA-256 of canonical JSON for the whole manifest.

Idempotence is state-based. A rerun is `no_changes` only when every requested
state already matches exactly. If only part of a prior transaction is present,
the old version/baseline normally conflicts and a fresh reviewed manifest is
required.
Readback also enforces target membership independently of operation
idempotence: an entry without `ensure_collection_membership` must still match
its bound `expected_target_membership`, while a satisfied membership operation
must observe the parent present in the target collection.

Transaction profiles are derived rather than declared. Collection membership,
parent `shortTitle`, and child-note operations may share one `db_atomic`
manifest. PDF operations cannot share a manifest with those database-only
operations. A PDF-only manifest may describe already-satisfied rows for
readback, but preview refuses more than one live `needs_write` PDF. Compile a
multi-row repair source with one reviewed `--parent-key` at a time. The single
PDF import calls Zotero's public `importFromFile()` without a bridge-owned outer
transaction because that API owns its own database and storage transaction.
An attachment failure is `unknown` until readback proves the result; only a
failed `db_atomic` write whose state digest equals its preflight baseline may be
reported as `rolled_back`.

## Commands

Compile an existing attachment-repair manifest:

```bash
python scripts/zotero_declarative_bridge.py compile-attachment-repair \
  /absolute/zotero_attachment_repair_manifest.json \
  /absolute/zotero-transaction.json \
  --transaction-id doe-pdf-repair-20260805
```

Compile a note-migration manifest. This uses only Local API GET requests to
bind keyed target ancestry and current parent identity:

```bash
python scripts/zotero_declarative_bridge.py compile-note-migration \
  /absolute/migration_manifest.json \
  /absolute/zotero-note-transaction.json \
  --transaction-id doe-note-migration-20260805
```

Compile collection membership for existing parents, again using only GET:

```bash
python scripts/zotero_declarative_bridge.py compile-membership \
  /absolute/zotero-membership-transaction.json \
  --transaction-id doe-membership-20260805 \
  --group-id 1234567 --library-id 2 --library-name 'Example Research Library' \
  --local-collection-id 40 --collection-key COLL0001 \
  --parent-key PARENT01 --parent-key PARENT02
```

Compile one reviewed parent `shortTitle`. The compiler first reads the live
parent and refuses collection, version, or old-value drift:

```bash
python scripts/zotero_declarative_bridge.py compile-short-title \
  /absolute/zotero-short-title-transaction.json \
  --transaction-id doe-short-title-20260805 \
  --group-id 1234567 --library-id 2 --library-name 'Example Research Library' \
  --local-collection-id 40 --collection-key COLL0001 \
  --parent-key PARENT01 --expected-parent-version 17 \
  --expected-old-value "" --new-short-title "Reviewed short title"
```

An already-applied manifest remains idempotent even though Zotero has advanced
the item version: exact equality with `new_short_title` is `satisfied`. Any
non-matching value still requires the bound old value and version and otherwise
fails closed as drift.

Execute after separate plugin installation:

```bash
python scripts/zotero_declarative_bridge.py validate /absolute/zotero-transaction.json
python scripts/zotero_declarative_bridge.py probe --capability-file /absolute/profile/zotero-declarative-bridge-capability.json
python scripts/zotero_declarative_bridge.py preview /absolute/zotero-transaction.json \
  --capability-file /absolute/profile/zotero-declarative-bridge-capability.json \
  --receipt /absolute/preview-receipt.json
python scripts/zotero_declarative_bridge.py apply /absolute/zotero-transaction.json \
  --capability-file /absolute/profile/zotero-declarative-bridge-capability.json \
  --preview-receipt /absolute/preview-receipt.json \
  --receipt /absolute/apply-receipt.json --yes
python scripts/zotero_declarative_bridge.py readback /absolute/zotero-transaction.json \
  --capability-file /absolute/profile/zotero-declarative-bridge-capability.json \
  --receipt /absolute/readback-receipt.json
```

A schema-valid structured HTTP failure for `preview`, `apply`, or `readback`
is evidence and is therefore written to the requested receipt with exclusive
create semantics and mode `0600`. The command exits nonzero and stderr contains
only `error_code`, `commit_state`, and the receipt path; private inspection
state, item keys, source paths, and hashes remain inside the receipt. Treat
`unknown` and `committed_unverified` as requiring a fresh authenticated
readback. `rolled_back` is evidence that the post-failure database state digest
matched the bound preflight baseline, not evidence that no write was attempted.

All manifests and receipts contain private Zotero state. Keep them outside the
public repository in a user-only directory.
