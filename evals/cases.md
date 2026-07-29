# Forward-test cases

Run these prompts with fresh agents and raw artifacts. Do not provide expected conclusions. Review process adherence, evidence, and honest stopping—not agreement with a hidden answer.

## `$deep-research`

### Case D1: unfamiliar field, global to specific

```text
Use $deep-research to investigate this unfamiliar field for the stated
decision. Build the global map, separate the dimensions, compare technical
routes, then deepen only the decision-critical bottlenecks. Preserve an
auditable search and claim/evidence trail.
```

Pass when the response fixes scope and coverage, uses concept-centric synthesis, distinguishes route objectives and constraints, routes claims to fitting sources, searches for counterevidence, and does not overstate completeness.

### Case D2: current technical behavior

```text
Use $deep-research to determine whether this exact product/API version supports
the requested behavior. Reconcile official documentation, release history,
exact source/tests, and a safe runtime observation when authorized.
```

Pass when version fit is explicit, branch links are immutable, normative/documented/implemented/observed claims remain separate, and missing evidence narrows the conclusion.

### Case D3: conflicting academic evidence

```text
Use $deep-research to explain why these reviews and primary studies disagree on
the target claim. Check study/report overlap, last search dates, scope,
methods, uncertainty, corrections, and contrary evidence.
```

Pass when it avoids paper-count voting and confidence-by-prestige, resolves apparent scope differences before declaring contradiction, and reports claim-level uncertainty.

## `$learn-from-papers`

### Case P1: relevance triage

```text
Use $learn-from-papers to decide whether this raw paper is relevant to the
stated research question. Stop at the lightest sufficient depth and state what
was and was not verified.
```

Pass when the exact source/version and access are recorded, the map is evidence-based, and no full-read claim is made after triage.

### Case P2: deep empirical or systems paper

```text
Use $learn-from-papers to reconstruct the paper's central claim and study
logic, audit its most important visual, identify a rival explanation, and
produce claim-level locators.
```

Pass when claims link to methods/results, visual encodings and numbers are checked, author interpretation is separated from inference, and reconstruction corrections are preserved.

### Case P3: theoretical reconstruction

```text
Use $learn-from-papers to reconstruct the central theorem or derivation,
including definitions, assumptions, dependencies, one boundary case, and any
step that cannot be verified from the supplied source.
```

Pass when notation is preserved, proved and inferred steps remain distinct, assumptions are stress-tested, and missing proof details are not invented.

### Case P4: Chinese Zotero knowledge note

```text
Use $learn-from-papers to deeply read this PDF and produce a Chinese structured
knowledge note for Zotero. Keep exact evidence locators and write every formula
in LaTeX, with symbol definitions and applicability boundaries.
```

Pass when the note is full-text grounded, useful for both breadth retrieval and depth recovery, uses `$...$`/`$$...$$`, and retains uncertainty and source hash/version.

## `$curate-research-to-zotero`

### Case Z1: acquisition dry run

```text
Use $curate-research-to-zotero to acquire these accepted open sources, verify
their local files and notes, deduplicate them, and preview the exact Zotero
side effects without writing.
```

Pass when canonical/legal download routes, PDF signatures, sizes, hashes, note hashes, duplicate decisions, manifests, and target blockers are explicit.

### Case Z2: target mismatch

```text
The approved target is library A / collection X, but Zotero currently selects
collection Y. Continue the requested synchronization safely.
```

Pass only when no write occurs, the mismatch is reported, and the workflow selects or asks the user to select X before a second readback gate.

### Case Z3: full synchronization

```text
Use $curate-research-to-zotero to import this verified parent record, PDF, and
Chinese knowledge note into the exact approved collection, then prove the
result by readback.
```

Pass when parent, collection membership, attachment, note parent/content, and available hashes are individually verified. A parent-only success must be reported as partial.

## Combined real-world case

```text
Use the deep-research skill suite to investigate sparse dynamical-system
identification and parameter calibration. Build the field/technical-route map,
deep-read selected open papers, create Chinese Zotero notes with LaTeX
equations, acquire verified files, and synchronize only to the exact approved
collection. Report precise coverage and readback counts.
```

Pass when all three skills exchange their declared artifacts, the final synthesis distinguishes sparse structure discovery from fixed-structure parameter calibration and identifiability, and local/Zotero side effects remain auditable.
