# Zotero synchronization workflow

Use the installed Zotero integration and its documented routes. Probe capabilities at runtime because local API, connector, and cloud API permissions differ.

## Target gate

1. Probe Zotero and retrieve libraries/collections read-only.
2. Resolve the approved library ID and exact collection path/key.
3. Immediately before import, retrieve the connector's selected target.
4. Require equality on library identity and collection key, and require item/file editability as needed.
5. Abort the batch if the collection is missing, selection differs, or permissions are insufficient.

Some Zotero local APIs are read-only and some connectors save to the currently selected target. Do not infer collection-creation or explicit-target capabilities. If a supported collection-create route is absent, ask the user to create/select the collection in the desktop UI, then repeat the readback gate.

Feature-probe existing-note updates instead of assuming that every Zotero
release has the same local-API capabilities:

1. inspect `GET /api/` for a per-instance `Zotero-Server-ID`;
2. check for the documented local authorization route;
3. use an authorized, version-guarded local `PATCH` only when both are present;
4. otherwise use the official Zotero Web API with a dedicated key supplied
   through a local environment variable, or stop for a manual Desktop update.

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
first. It never edits SQLite and requires `--yes` for a write.

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
