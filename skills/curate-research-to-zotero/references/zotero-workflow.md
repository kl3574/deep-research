# Zotero synchronization workflow

Use the installed Zotero integration and its documented routes. Probe capabilities at runtime because local API, connector, and cloud API permissions differ.

## Target gate

1. Probe Zotero and retrieve libraries/collections read-only.
2. Resolve the approved library ID and exact collection path/key.
3. Immediately before import, retrieve the connector's selected target.
4. Require equality on library identity and collection key, and require item/file editability as needed.
5. Abort the batch if the collection is missing, selection differs, or permissions are insufficient.

Local-API write support varies by the running Zotero build, while some
connectors save only to the currently selected target. Do not infer
collection-creation or explicit-target capabilities. If a supported
collection-create route is absent, ask the user to create/select the collection
in the desktop UI, then repeat the readback gate.

For existing-note updates and approved child-note creation under an existing
parent, Zotero Desktop's official
[**Tools → Developer → Run JavaScript** surface](https://www.zotero.org/support/dev/client_coding/javascript_api)
is a no-key route when the user can paste and run the generated script in the
app. Prefer it for an approved local batch because all notes can be rechecked
and updated or created inside one Zotero database transaction:

1. stage and validate migration manifest v2, including `group_id`,
   `library_id`, `library_name`, `local_collection_id`, `collection_key`, and
   the complete `collection_path`; the staging script derives these from both
   the keyed group collection hierarchy and the currently selected Desktop
   target, and refuses a mismatch. It paginates instead of accepting a
   100-item prefix and snapshots every live collection parent plus each
   parent's complete child-item, child-note, and attachment keys. For an
   approved parent-specific source file, pass an absolute-path JSON
   `parent_key -> schema-9 HTML path` map with `--parent-note-map`. Zero live
   child notes produces `create_verified`; exactly one uses the same source as
   a curated override; more than one remains `blocked_multiple_notes`. A valid
   existing schema-9 note (or a curated override equal after Zotero's storage
   trim) is
   `unchanged_verified`; in the latter case, stage the exact live bytes so the
   unchanged file and old/new hashes remain identical. Only a genuinely
   changed, valid projection is `staged_verified`. Both statuses stay in the
   complete preflight inventory, but only `staged_verified` is a mutation
   candidate. After a successful creation, rerunning the same parent map sees
   the single matching note and produces `unchanged_verified`, including
   verified Zotero storage normalization: outer/source whitespace, implicit
   table bodies, attribute-free `thead`/`tbody`/`tfoot` wrappers that contain
   only ordered `tr` children, attribute-free single-paragraph table-cell
   wrappers, and whitespace-only HTML-ASCII text nodes adjacent to an
   attribute-free `br`. The comparison still preserves row and cell order,
   `th` versus `td`, section attributes or non-row children, nonbreaking
   spaces, attributed breaks, preserved-whitespace contexts, and every other
   meaningful element and attribute;

   ```json
   {
     "PARENT01": "/absolute/path/to/PARENT01.schema9.html"
   }
   ```

   The map itself is passed as
   `prepare_note_migration.py --parent-note-map /absolute/parent-note-map.json`;
   every mapped HTML path must be absolute, readable, and independently valid
   schema-9 HTML.

2. before branching on child-note count, bind every parent to one verified
   local PDF attachment, its parent,
   link mode, PDF magic bytes, and SHA-256. Multiple PDF children are
   ambiguous and block staging unless an approved JSON
   `parent_key -> attachment_key` map is supplied with
   `--pdf-attachment-map`; never select the first API result silently;
3. keep exact original-HTML backups and their SHA-256 values outside the public
   repository. Use a fresh directory owned by the current user and not writable
   by group/other users; reserved subdirectories and every artifact are created
   exclusively, and a missing, deleted, unreadable, or non-PDF source blocks
   staging instead of producing a partially bound apply candidate;
4. generate a manifest-hash-bound dry-run script:

   ```bash
   python scripts/render_zotero_desktop_runner.py \
     /absolute/migration_manifest.json \
     --require-auto-sync-enabled
   ```

5. keep the approved collection selected, paste the generated code into Run
   JavaScript, and run it; inspect the JSON report written beside the manifest;
6. generate the apply runner:

   ```bash
   python scripts/render_zotero_desktop_runner.py \
     /absolute/migration_manifest.json \
     --apply \
     --require-auto-sync-enabled
   ```

   These examples use `--require-auto-sync-enabled` because the approved
   invariant is that automatic sync must remain on. The option is embedded
   independently into each generated runner, so pass it when rendering both
   dry-run and apply scripts; omit it from both only when that invariant was
   not approved.
   With this flag set, both dry-run and apply paths fail before manifest/live
   preflight when `sync.autoSync` is false, and the dry-run report includes
   `syncState.autoSyncObserved`.

7. apply only after the dry-run verifies every inventory note or creation,
   parent, complete child inventory, approved attachment/PDF, staged schema-9
   HTML, version, collection membership, and exact selected target. Updates
   additionally require the exact old backup; creations require the staged
   parent version, a stable parent-bibliographic snapshot hash, and a still-empty
   child-note inventory. The snapshot preserves `itemType`, every native
   bibliographic field, and creator order, while excluding operational fields
   already guarded elsewhere (`key`, `version`, timestamps, access date,
   citation key, collection/tag/relation membership, and sync metadata). The
   renderer
   reruns the schema validator and requires the uniquely labelled Chinese
   `全文SHA-256` field to equal the file hash. It also requires the attachment's
   current `getFilePathAsync()` result to equal the manifest PDF path; a
   redirected attachment cannot pass merely because the old file still
   exists. The runner re-enumerates the
   collection and every parent's notes and attachments before the batch and
   again at transaction start, so a newly added second note blocks rather than
   bypasses ambiguity handling. It revalidates all previously verified
   entries (`staged_verified`, `unchanged_verified`, and `create_verified`)
   inside one transaction, then updates only the manifest-bound
   `staged_verified` keys and creates only the verified zero-note parents with
   `new Zotero.Item("note")`, `libraryID`, `parentKey`, `setNote()`, and
   `save()`. It never calls `save()` for `unchanged_verified`. If every note is
   unchanged, apply returns
   `no_changes` without acquiring the sync barrier or opening a write
   transaction. The report keeps update and creation counts separate and
   records updated note keys, creation parent keys, and newly assigned note
   keys.
   The transaction rolls
   back on an in-transaction failure, rechecks parent membership and target
   identity again at transaction start, and performs committed local-database
   readback. That readback must reload each updated or created note and verify
   its assigned key, item type, deletion state, parent, content, and collection
   membership, then re-enumerate the post-create child inventories. Existing
   notes require a nondecreasing object version and created notes require a
   valid nonnegative local object version; a newly created unsynced note
   normally remains at version `0`. Readback must
   not require the object version to advance inside the sync barrier: Zotero's
   [sync contract](https://www.zotero.org/support/dev/web_api/v3/syncing#local_object_versions)
   leaves the server object version unchanged for a local edit and advances it
   only after upload. Record local commit verification separately from later
   server-version advancement. If a
   post-commit callback throws, it inspects all notes and reports
   committed/rolled-back/unknown instead of assuming rollback. It waits for an
   active sync to finish, uses Zotero's in-memory
   `Sync.Runner.delayIndefinite()` barrier only across the transaction and
   readback, leaves any existing automatic-sync timer intact, then releases the
   barrier in `finally`; an idempotent watchdog also releases a stuck lease,
   and lease expiry is a non-success outcome. The persistent automatic-sync
   preference is never changed, is checked again at transaction start and
   completion, and is reported before/after;
8. independently read back through the local API, update the manifest from
   observed state, and verify that the original automatic-sync preference was
   preserved. This proves local persistence, not cloud synchronization. Claim
   cloud synchronization only after a separate authenticated Web API readback
   shows the uploaded content and an advanced server object version. If sync
   was intentionally paused outside this runner, restore it before any remote
   synchronization check.

Do not paste `zotero_desktop_note_migration.js` directly: it is a template and
has no bound manifest. A dry-run writes only its diagnostic report, not Zotero
data. The renderer rejects a report path that aliases the manifest, staged
HTML, a source PDF, or the runner template, and it will not overwrite an
existing evidence report. The App runner repeats the fresh-path check before
the batch and before persistence; if persistence itself fails, it returns the
full report in the Run JavaScript result pane. Zotero's `setNote()` trims outer
whitespace, so the report records both
the staged-source SHA-256 and the expected stored SHA-256 when they differ.
Zotero may also normalize valid table markup and source whitespace. Accept a
non-byte-exact readback only when a deterministic DOM projection preserves the
schema root, ordered text chunks, headings, ordered table rows and cell tags,
LaTeX blocks, links, images, and list content. Normalize only the verified
attribute-free table-section, table-cell paragraph, and `br`-adjacent
HTML-ASCII whitespace cases above; reject section attributes, non-row
children, row/cell changes, nonbreaking spaces, attributed breaks, and
preserved-whitespace changes. Record both hashes and the normalization. Never
relax a content, parent, collection, item-type, deletion, or version check.

Feature-probe HTTP/API updates instead of assuming that every Zotero release
has the same local-API capabilities:

1. inspect `GET /api/` for a per-instance `Zotero-Server-ID`;
2. treat an absent server ID as no supported local-write protocol in that
   running instance;
3. do not probe `/api/local/authorize` with `OPTIONS`: authorization is a
   stateful `POST` that may show a user confirmation dialog;
4. only in approved apply mode, request a local key with the server ID and use
   a version-guarded local `PATCH`; never print or persist the returned key;
5. for a multi-note batch, require a reusable authorization (`Always Allow`)
   before the first mutation instead of consuming a single-use key partway;
6. otherwise use the official Zotero Web API with a dedicated key supplied
   through a local environment variable, use the Desktop runner above, or
   stop.

For the Web route, dry-run must authenticate with `GET /keys/current`, verify
read/write access to the exact group, and preflight every selected remote note,
parent, collection membership, old-content hash, and object version before the
first mutation. Do not treat the mere presence of an environment variable as a
permission check.

The Connector's selected-target response exposes a local numeric collection ID
and tree path but not a trustworthy `group_id`/collection-key binding.
Therefore the HTTP/Web updater separately resolves the explicit group/key
hierarchy and shows both halves in dry-run, but refuses apply by default. Only
after the user explicitly approves the displayed `group_id` and
`collection_key` as the authoritative API target may apply add:

```bash
python scripts/update_existing_note.py /absolute/migration_manifest.json \
  --yes \
  --confirm-explicit-api-target
```

This flag acknowledges the missing local-ID-to-key binding; it does not skip
any note, parent, path, permission, hash, version, backup, or readback check.
Prefer the Desktop runner whenever the user can operate the app because it
binds the local collection ID and key to the same live collection object.
HTTP/Web batches have no cross-object transaction: the updater therefore
accepts the same manifest v2 contract as the Desktop renderer, recomputes the
PDF and staged-note validation instead of trusting summary metadata, and
revalidates both local and remote explicit collections plus their full
parent/child inventories around each Web mutation. Immediately before the
request, it resolves the live local attachment file URL, re-hashes that file,
and re-reads the local note's type, parent, version, and old-content hash. This
blocks an unsynchronized local edit rather than letting a stale remote PATCH
create a sync conflict. It stops on the first conflict and must report an accepted or
unknown current write separately from previously verified results. Manifest
v1 is rejected rather than interpreted with weaker fallback semantics.

For an existing child-note update, require the expected note key, parent key,
old content hash, new content hash, exact collection membership, an old-HTML
backup, and `If-Unmodified-Since-Version`. Stop on `412`; never retry by
overwriting a concurrent change. The current Connector import/session routes
must not be used to manufacture duplicate parents as an update workaround.

## Preview

Before the first write, show:

```text
library name/id
collection path/key
parents to add
PDF attachments to add
metadata-only records
duplicates skipped
conflicts blocked
validated manifest path
```

If the user already explicitly approved this exact target and batch, proceed after the live target gate. A prior general request to “use Zotero” is not approval for an unrelated currently selected collection.

## Import patterns

Use the best supported pattern:

- BibTeX/RIS connector import for parent metadata; when a `file` field is supported without a base URI, use an absolute local path.
- A verified BibTeX `annote`/`notes` mapping or documented child-note route for the structured literature note.
- A documented create-parent plus attachment-upload flow when the connector exposes it.
- A cloud API only with existing authorized credentials and explicit target permissions.

When the local Zotero version supports `/connector/saveItems` plus `/connector/saveAttachment`, [import_zotero_bundle.py](../scripts/import_zotero_bundle.py) provides a one-item, dry-run-first path. It intentionally refuses existing matches instead of updating them and verifies the parent, exact collection, child note, attachment, and optional stored-file hash.

For a version-guarded existing-note migration, use
[update_existing_note.py](../scripts/update_existing_note.py) in dry-run mode
first. It supports an authorized local route when the runtime advertises a
server ID and a Web API fallback when a dedicated key is available. It never
edits SQLite, never stores either key, and requires `--yes` for a write. The
runner revalidates `verify_local_source_contract` for every verified entry before
any backup or patch operation; if any recheck fails, apply exits as
`preflight_failed` without mutating remote or local note content.

Never expose credentials. Do not use direct SQLite edits as an ordinary fallback.

Connector imports can create a parent even when attachment handling fails. Therefore:

- inspect the returned parent records;
- query children;
- verify attachment item type and file availability;
- compare source and stored hashes where accessible.

Do not assume every BibTeX `note` field creates a child note: translators may map identifier-like content into an Extra field. Test the exact importer/version, prefer its explicit annotation field, and read back the child note.

When writing Zotero HTML notes, preserve LaTeX source. A compatible display-math representation may use `<pre class="math">$$...$$</pre>`; inline expressions retain `$...$`. Verify the exact Zotero version by readback instead of assuming rendered appearance proves the source survived.

Before any note write, validate the staged HTML against
[zotero-note-html.md](zotero-note-html.md). The canonical Markdown note and the
Zotero HTML projection are different artifacts and have separate hashes.

## Duplicate behavior

Search the target library by DOI/identifier and canonical title before import. Skip exact matches. Put ambiguous matches in the preview. Do not delete or merge old records, and do not “fix” an existing record by overwriting it without separate approval.

## Readback checklist

For each batch ID:

```text
approved target matched immediately before write
parent item key returned and found
exact collection membership found
title/identifier/year/version matched
attachment child key found or metadata_only explained
stored file readable
stored hash equals staged hash, or copy transformation explained
requested tags/notes found
structured note is a child of the intended parent and its normalized content matches
manifest updated from observation
```

Report counts separately:

`staged / file-verified / parent-imported / attachment-imported / readback-verified / metadata-only / failed`

A `201 Created`, successful parent search, or visible citation is insufficient to claim full PDF synchronization.

## Versioned batch and corpus snapshot

Use [curation-batch.md](curation-batch.md) for the strict `CurationExecution/v1`
path through readback. Target identity mismatch or mutable-state drift invalidates
the old approval. `partial_commit` and `readback_mismatch` are terminal failures.
The existing importer remains unchanged.

`snapshot_zotero_collection.py` is a read-only local-API export for research. It
omits note bodies, abstracts, full text, attachment locations, and credentials.
A temporary knowledge graph is not a Zotero note and receives no write authority.
Its `--base-url` accepts either a loopback origin such as
`http://127.0.0.1:23119` or the equivalent API root
`http://127.0.0.1:23119/api`; both are normalized to the origin. Other paths,
credentials, queries, fragments, and non-loopback hosts are rejected.
