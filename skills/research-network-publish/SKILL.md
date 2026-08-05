---
name: research-network-publish
description: Validate a finished research knowledge network and render deterministic, self-contained HTML, optionally using a reviewed research map. Use when a finished network needs private or redacted publication. Not for research, browsing, graph mutation, or Zotero writes.
---

# Research Network Publish

Render final research state without changing it. Read
[references/contracts.md](references/contracts.md) for input schemas, privacy
modes, projection fields, and output guarantees.

## Required workflow

1. Accept one final `KnowledgeNetwork/v1` and, optionally, a reviewed
   snapshot-bound `ResearchMap/v1`.
2. Run `validate` for schema, digest, snapshot binding, references, credentials,
   and the selected privacy mode.
3. Run `render` directly to the final new target. Do not stage in a system
   temporary directory or move/copy output afterward.
4. Inspect the self-contained HTML locally and preserve the private JSON inputs
   separately.

Use `scripts/render_network_html.py --help` for commands.

## Gates and boundaries

- `public-redacted` removes internal IDs, paths, hashes, Zotero keys, and private
  content. `private` retains approved IDs/locators. Both reject credentials and
  omit note bodies and full text.
- Output is deterministic and offline: no clocks, randomness, network calls,
  remote fonts, CDN assets, or raw input JSON.
- Refuse an existing target. Publish through a sibling temporary file using
  write, flush, file `fsync`, `os.replace`, and directory `fsync`; never use a
  cross-filesystem replace or non-atomic copy. Report cleanup and post-commit
  `fsync` failures exactly as defined in the contract.
- Validation or rendering failure is not a publication.
- This skill does not discover, read, interpret, resolve, or mutate research and
  never writes Zotero.
