# Zotero literature-note HTML contract

This is the Zotero projection of the canonical paper card and claim ledger from
`$learn-from-papers`. It is a retrieval surface, not an independent source of
truth.

This document describes the legacy structured-note layout. A reviewed
`PaperUnderstandingNoteInput/v1` uses the stricter deterministic
[`PaperKnowledgeNote/v2`](paper-knowledge-note-v2.md) pyramid projection. The
shared validator dispatches by `data-note-contract="PaperKnowledgeNote/v2"`.
Neither layout authorizes changing a parent item's bibliographic `title` or
`shortTitle`.

## Root and section contract

Use one root and one title:

```html
<div data-schema-version="9">
  <h1>文献笔记｜&lt;paper title&gt;</h1>
  ...
</div>
```

The legacy full-text form above remains valid without a root access marker. A
metadata-only projection is a separate, explicit branch:

```html
<div data-schema-version="9" data-access-level="metadata_only">
  <h1>文献笔记｜&lt;paper title&gt;</h1>
  ...
</div>
```

`data-access-level="metadata_only"` is not a decorative tag. It must agree
with `访问层级：metadata_only`, and `资料与阅读状态` must visibly contain
`全文状态：未获取全文`. Its `阅读深度` is `map`. The claim table retains the
exact header for deterministic projection but has no data rows. The entire note
must contain no local-PDF field, full-text/PDF hash, 64-hex content hash, or
full-text evidence claim. `溯源` instead requires nonempty `元数据来源` and a
dated `元数据核验时间：YYYY-MM-DD`. Metadata-derived orientation is never
full-text evidence.

`PaperKnowledgeNote/v2` is always a full-text projection and cannot use the
metadata-only marker. A legacy full-text note, whether its root marker is absent
or explicitly `full_text`, continues to require exactly one
`全文SHA-256：<64 lowercase hex>` and at least one evidence claim row.

The following Chinese section names are required, in this order:

1. `资料与阅读状态`
2. `为什么重要`
3. `一句话结论`
4. `心智模型`
5. `关键主张与证据`
6. `方法或推导`
7. `结果`
8. `假设、失败边界与竞争解释`
9. `知识图谱关系`
10. `复用`
11. `溯源`

For a `reconstruction` note, also include `完整性与纠错日志` before `溯源`.
An appendix may preserve useful earlier exposition, images, or teaching
material, but it cannot replace the required sections.

## Required fields

`资料与阅读状态` records:

- canonical title, authors, year, venue, and DOI or other stable identifier;
- publication/version status and access level;
- the real local full-text path and SHA-256, when a file was read;
- `map`, `evidence`, or `reconstruction` reading depth;
- verification time and offline/current-status limitations.

For metadata-only notes, replace the local full-text path/hash with the exact
visible missing-full-text declaration above; do not insert a placeholder or
fabricated hash merely to satisfy the full-text branch.

`关键主张与证据` is a table. Each row includes:

```text
Claim ID
Nature
Claim
Evidence and exact locator
Conditions
Confidence and rationale
```

Claim IDs are stable and unique within the note (`C1`, `C2`, ...). Nature is
one of:

- `source-stated`
- `agent-inferred`
- `externally-supported`
- `unresolved`

Confidence is `high`, `medium`, or `low`, followed by a short rationale. Do not
upgrade inherited or unverified material merely to fill the table.

For combined main-text/supplement files, use dual locators such as:

```text
补充材料 p.19 | PDF 实体页 25 | Eq. (27)
```

## Chinese and mathematics

- Explanatory prose is Chinese unless the user requests another language.
- Preserve original terminology, notation, units, and version labels.
- Inline mathematics uses `$...$`.
- Display mathematics uses:

```html
<pre class="math">$$\dot{\mathbf X}=\Theta(\mathbf X)\Xi$$</pre>
```

- Escape LaTeX alignment ampersands as `&amp;` in HTML source.
- Do not substitute Unicode glyphs such as `Ẋ`, `Θ`, `Ξ`, `²`, `³`, or
  `‖·‖₀` for LaTeX mathematics.
- After every consequential display equation, state in Chinese its symbols,
  role, assumptions, and exact source locator.

## Reconstruction-only completeness

A reconstruction note records:

- total pages and main-text/supplement page mapping;
- formulas, figures, and tables actually checked;
- OCR or text-layer limitations;
- unresolved source inconsistencies;
- a correction log in the form
  `初始理解 -> 源文复核 -> 修正及影响`.

Unknown counts or statuses are written as `unresolved`; never guess.

## Provenance and readback

`溯源` records the paper-card/evidence-ledger identity, real local file path and
hash, source note key/version when migrating, and whether agent inference is
explicitly marked.

After a Zotero write, verify:

- exact parent item and collection;
- child note key and parent;
- normalized read-back HTML or a stable digest;
- source and stored note digests;
- any transformation performed by Zotero.

Structure validation cannot prove scientific correctness. Entailment,
conditions, and locators still require source-level review.
