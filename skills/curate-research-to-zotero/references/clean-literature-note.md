# Clean Zotero literature-note contract

`ZoteroCleanLiteratureNote/v1` is the forward authoring contract for literature
notes. It owns Zotero HTML projection and static content hygiene. Legacy
`PaperKnowledgeNote/v2` remains readable for migration but is not the template
for new notes.

## Content boundary

Keep only source-related understanding in the synchronized note: applicable
scenario, bounded conclusion, assumptions, method, equations, results,
limitations, and evidence locators. A natural-language evidence limitation such
as `该判断仅由摘要支持` belongs in the note because it changes interpretation.

Keep workflow state outside the note in a private sidecar: hashes, local paths,
timestamps, run or transaction IDs, draft/review/apply/readback state, tool
versions, download/OCR state, and errors. `data-schema-version` is required
Zotero structure, not workflow state. Preserve `data-citation-items` only when
surviving Zotero citation or annotation nodes require it. Add no custom state
attributes.

## Canonical math projection

Use exactly:

```html
<div data-schema-version="9">
  <h1>适用场景与结论</h1>
  <p>行内公式 <span class="math">$S_i=V_i/V$</span>。</p>
  <pre class="math">$$S_{T_i}=1-V_{\sim i}/V$$</pre>
</div>
```

- Put inline math directly inside `p` as `<span class="math">$...$</span>`.
- Put display math outside paragraphs/headings as
  `<pre class="math">$$...$$</pre>`.
- Do not store bare dollar-delimited text, `\(...\)`, `\[...\]`, rendered
  KaTeX/MathML/SVG, IDs, or custom attributes on math nodes.
- Escape raw LaTeX once as HTML text. In particular, `&` becomes `&amp;` and
  `<` becomes `&lt;`. Let the JSON serializer escape backslashes; do not
  pre-double them.
- Keep stable formula IDs in the private sidecar. Visible display numbering may
  use a supported LaTeX `\tag{...}`.
- Omit Zotero's database wrapper `<div class="zotero-note znv1">` from the
  `note` value passed to the API or bridge.

Zotero 9.0.6 pins note-editor math nodes to
[`span.math` and `pre.math`](https://github.com/zotero/note-editor/blob/107ab75c3247c6584bda2303ecbddf4b317fdd2d/src/core/schema/nodes.js#L156-L174).
Its serializer emits schema 9 for math-capable notes without underline
annotations; see the official
[`buildToHTML` downgrade](https://github.com/zotero/note-editor/blob/107ab75c3247c6584bda2303ecbddf4b317fdd2d/src/core/schema/utils.js#L58-L68).

## Validation and roundtrip

Run before reviewed-batch compilation:

```bash
python scripts/clean_literature_note.py validate /private/note.schema9.html
```

After readback, compare ordered decoded formula kinds and payloads rather than
requiring byte-identical HTML:

```bash
python scripts/clean_literature_note.py roundtrip \
  /private/expected.schema9.html /private/readback.schema9.html
```

Zotero can trim, normalize text to NFC, insert formatting whitespace, or change
compatible schema metadata. A data readback proves node preservation, not KaTeX
render success; visually inspect representative complex formulas in Zotero.

Zotero 9's Local API is read-only. Reviewed writes use the constrained Desktop
bridge; Local API writes begin in Zotero 10. See the official
[Local API documentation](https://www.zotero.org/support/dev/web_api/v3/local_api).

## Fixed-pane readability

Math nodes contain mathematical expressions, not symbol explanations or prose.
Keep definitions, assumptions, interpretation, and warnings in adjacent Chinese
paragraphs. Short `\\text{...}` labels inside cases and genuine operators such as
`\\operatorname{Var}` remain valid, but wrapping an explanatory sentence in
`\\text{...}` does not turn it into mathematics.

For a long expression or several relations, use `aligned` or `gathered` and put
one semantic relation on each line. Prefer several coherent display nodes when
the lines express separate steps. This is a readability strategy, not a static
rendering proof: character count, source width, or byte length cannot predict
KaTeX layout in Zotero's fixed pane. Open representative notes in the actual UI
and check line breaks, clipping, horizontal overflow, and KaTeX errors.
