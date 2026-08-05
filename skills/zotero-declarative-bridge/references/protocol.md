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
  at 100, and operations at three per parent.
- Schemas reject unknown fields. Operation names are an enum, not dispatchable
  JavaScript names. No `eval`, `Function`, module path, SQL, delete, or arbitrary
  metadata operation exists.

## Manifest

`ZoteroDeclarativeTransaction/v1` binds:

- exact local library ID, library type/type ID/name, editability;
- exact collection ID/key and every keyed path component;
- exact parent key, version, type, title, normalized DOI, target membership,
  and SHA-256 of that identity object;
- complete child-note or attachment baselines for the operation that needs it;
- exact old/new note hashes or local PDF path/size/magic/hash;
- SHA-256 of canonical JSON for the whole manifest.

Idempotence is state-based. A rerun is `no_changes` only when every requested
state already matches exactly. If only part of a prior transaction is present,
the old version/baseline normally conflicts and a fresh reviewed manifest is
required.

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
  --group-id 6588343 --library-id 2 --library-name wolfs \
  --local-collection-id 40 --collection-key KHQKFIWX \
  --parent-key ABCD1234 --parent-key EFGH5678
```

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

All manifests and receipts contain private Zotero state. Keep them outside the
public repository in a user-only directory.

