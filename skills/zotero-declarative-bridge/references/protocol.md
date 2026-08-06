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
- `resolve_collection` is a separate authenticated read-only action, not a
  manifest operation. It accepts exactly one internal group-library ID and one
  collection key, performs one composite keyed lookup, and returns only the
  exact inputs plus Zotero's numeric collection ID. It never lists or searches
  libraries or collections. Missing, ambiguous, deleted, non-group, or
  mismatched results fail closed without a write attempt.

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

### Reviewed batch compiler

`compile-reviewed-batch` is the only supported projection from
`ZoteroReviewedMutationBatch/v1`. The reviewed source must have exactly the
top-level fields `schema`, `status`, `created_at`, `private`, `source`, `target`,
`entries`, `summary`, `executable`, `execution_contract`, and
`manifest_sha256`. It must be private, non-executable, and have status
`reviewed_requires_bridge_compile`.

The currently supported source hash contract is `canonical-json-v1`:

- canonical JSON is UTF-8, key-sorted, compact, Unicode-preserving, and rejects
  NaN/Infinity;
- `manifest_sha256` hashes the top-level object without that field;
- `entry_sha256` hashes the entry without that field;
- parent `identity_sha256` hashes the reviewed parent object without that
  field;
- `new_short_title_sha256`, `new_sha256`, and `expected_old_sha256` hash the
  exact UTF-8 text bytes;
- digests may be 64 lowercase hexadecimal characters or the same value with a
  `sha256:` prefix.

`draft_entry_sha256` is an upstream provenance locator because the draft bytes
are not embedded in this schema. The compiler validates its digest form and
binds it through both `entry_sha256` and `manifest_sha256`; it does not claim to
recompute the absent draft. Any other hash basis fails closed and requires a
new named compiler contract rather than heuristic acceptance.

The source target binds the numeric local library ID, group identity,
collection key/version, and collection path names. The command additionally
requires the resolver-produced numeric collection ID. It reads the exact keyed
ancestry and live collection version, rejects name/key/version drift, and emits
the keyed path. For every parent it verifies the reviewed key/version/title/DOI
and target membership, then recomputes the bridge parent identity from live
item type and local library ID. For an update it also verifies the live
`shortTitle`, complete child-note inventory, note version, and exact old note
hash. Upstream-only source, draft, entry, parent, and short-title hashes are not
copied into the bridge transaction.

Only `ensure_parent_short_title` followed by `ensure_child_note` is accepted,
with at most one of each per parent and at most 100 key-sorted parents. The
result is one sealed database-only transaction; attachment and membership
operations are rejected rather than split or reordered.

The optional `decision-oriented` short-title policy requires exactly one
scenario/decision delimiter. For Chinese, each side must contain Chinese text
and the decision side must express a conclusion or warning; English has the
corresponding deterministic profile. A value equal to or merely contained in
the bibliography title after punctuation/spacing normalization is rejected as
a title abbreviation. This is a semantic-shape safeguard, not validation that
the stated research conclusion is scientifically correct.

Idempotence is state-based. A rerun is `no_changes` only when every requested
state already matches. Parent fields, membership, attachments, and note raw
content remain exact. A child note may additionally match by the strict Zotero
storage-equivalence fingerprint: it parses both HTML values as one schema-9
note DOM and ignores only serializer-added line-break indentation between block
nodes or at block boundaries. Element type/order, the complete attribute set,
visible characters, punctuation, meaningful internal spaces, math-node
type/order, and decoded LaTeX payload remain exact. Parse failure disables this
equivalence and falls back to the raw hash contract. Satisfied note decisions
report `content_match` as `exact` or `zotero_storage_equivalent`; child-note
state continues to expose the observed raw `sha256`. If only part of a prior
transaction is present, the old version/baseline normally conflicts and a
fresh reviewed manifest is required.

Receipt version evidence separates the reviewed precondition from Zotero's
currently observed sync-object version. Parent rows expose
`parent_version_precondition`, `parent_version`,
`parent_current_synced_version`, and `parent_version_sync_status`; child-note
rows expose the analogous `version_precondition`, `version`,
`current_synced_version`, and `version_sync_status`. Zotero does not increment
an object's sync version for an ordinary local edit. Until Zotero sync uploads
that edit, `version_sync_status` is `locally_modified_pending_sync`, the
observed `version` is the remote-base version, and `current_synced_version` is
null. The bridge never invents a future version or forces synchronization. A
later authenticated readback after Zotero sync reports the new synced version.
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
reported as `rolled_back`. Once Zotero's `executeTransaction()` promise returns,
the database commit is known to have completed. Any later verification or
response-construction failure is therefore `committed_unverified`, never
`unknown`, even if a concurrently active note editor immediately serializes a
note again. A true child-content/version conflict is returned as structured
`child_drift`, not a generic `internal_error`.

## Commands

Resolve Zotero's internal numeric collection ID after the exact group-library
ID and collection key have been explicitly authorized:

```bash
python scripts/zotero_declarative_bridge.py resolve-collection \
  --capability-file /absolute/profile/zotero-declarative-bridge-capability.json \
  --library-id 2 --collection-key COLL0001
```

The success output contains exactly `status`, `library_id`, `collection_key`,
and `collection_id`. The capability token is never printed. This command does
not accept a name, partial key, user-library fallback, or search mode; it cannot
be used to discover either input.

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

Compile a reviewed multi-parent short-title/note batch. The source may retain a
null pre-resolution `internal_collection_id`; the command must receive the exact
numeric ID returned by `resolve-collection` and will bind it into the output:

```bash
python scripts/zotero_declarative_bridge.py compile-reviewed-batch \
  /absolute/reviewed-mutations.json \
  /absolute/zotero-reviewed-transaction.json \
  --transaction-id reviewed-research-20260806 \
  --local-collection-id 40 \
  --source-hash-contract canonical-json-v1 \
  --short-title-policy decision-oriented \
  --short-title-language zh
```

Omit both short-title policy arguments to preserve the generic reviewed value
without applying research-title semantics. Supplying a language without a
policy, an unsupported language, or an unsupported hash contract fails closed.

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
readback. Never retry apply after `committed_unverified`: first quiesce active
note editors and synchronization, then read back the sealed manifest. A
`zotero_storage_equivalent` readback is acceptable only under the strict DOM
contract above; material prose, structure, attribute, list, or formula changes
remain drift. `rolled_back` is evidence that the post-failure database state
digest matched the bound preflight baseline, not evidence that no write was
attempted.

All manifests and receipts contain private Zotero state. Keep them outside the
public repository in a user-only directory.

## Reviewed literature-note prerequisite

The bridge does not author or reinterpret literature notes. For
`ZoteroReviewedMutationBatch/v1`, compilation fail-closes unless `new_html`
passes the sole content authority in
`$curate-research-to-zotero/scripts/clean_literature_note.py`. Workflow state
remains in the reviewed batch; only clean literature HTML reaches `setNote()`.
Generic declarative note transactions retain their narrower execution contract.

## Reviewed shortTitle preservation

`compile-reviewed-batch` rejects `expected_old_value == new_short_title` by
default. Use `--allow-unchanged-short-titles` only when a reviewed entry must
prove that an already-correct decision-oriented short title was preserved while
its child note changes. The compiler still validates the short-title policy,
retains the no-op operation for preview/readback, requires a changing note in
the same entry, and rejects every all-no-op entry.
