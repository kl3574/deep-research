# Learn-from-papers evaluations

This micro-gold evaluates scientific reading behavior, not prose style.

- `micro_gold_task.json` is safe to give the candidate. It contains questions,
  stable IDs, and the output contract, but no expected relation or evidence.
- `micro_gold_rubric.json` is evaluator-only during a candidate run. It contains
  gold relations, required locators, scope markers, conflicts, abstention, and
  hard gates. It is public repository content, not a secret or a
  cryptographically hidden artifact.
- `standard_evaluator.py` produces dimension-level diagnostics and hard-gate
  failures; it does not replace human semantic adjudication. It accepts the
  blind-task `LearnFromPapersDossier/v1` shape and producer-generated
  `PaperReadingDossier/v1` or finalized `PaperReadingReportSet/v2` artifacts.
- `fixtures/synthetic_wsr_paper.md` contains deliberate scope, sign, figure,
  citation, uncertainty, reproduction, and prompt-injection traps.

Run a paired evaluation with the same model, tools, and budget. Give the candidate
only the task manifest and source; withhold the rubric/evaluator through execution
isolation for that run. This is procedural blinding, not secrecy: a process that
can inspect the repository can read the gold files. Report each dimension and
hard gate, plus worst-of-N behavior; do not reduce the result to one average
score.

```bash
python evals/learn-from-papers/standard_evaluator.py \
  --candidate /tmp/candidate.json \
  --rubric evals/learn-from-papers/micro_gold_rubric.json
```

For a strict producer artifact, bind the private source provenance. A v2 report
set also needs its source dossier so that security handling is not inferred from
fields that v2 intentionally omits. `--verification-root` is mandatory for v2:
the evaluator reopens the content-addressed request and attestation artifacts
and calls the producer validator with `require_finalized=True`.

```bash
python evals/learn-from-papers/standard_evaluator.py \
  --candidate /tmp/report-set-v2.json \
  --rubric evals/learn-from-papers/micro_gold_rubric.json \
  --bundle /tmp/paper-source-bundle.json \
  --source evals/learn-from-papers/fixtures/synthetic_wsr_paper.md \
  --dossier-context /tmp/paper-reading-dossier-v1.json \
  --verification-root /tmp/verification-root
```

A plain `project-report-set` output, a prepared/partially attested set, or a set
without its verification root cannot pass. The positive integration fixture
uses the public `prepare-attestations -> attest --report-id ->
finalize-attestations` flow and at least two external verifier contexts.

Every supplied answer must cover all locators designated for its rubric atom.
The private rubric explicitly uses `none_or_all_required` for `not_tested`: no
evidence is an admissible abstention, but partial evidence is not. Conflict
retention always requires all designated conflict locators, even for
`not_tested` atoms.

## PaperUnderstanding semantic evaluation

`understanding_evaluator.py` is an independent second gate for final
`PaperUnderstanding/v1` artifacts. It reports producer schema validation and
semantic quality separately; schema validity does not add points to the
semantic score. The fixture-specific rubric checks applicability, workflow
nodes and formats, data-flow edges, mathematical and algorithmic dependencies,
bounded conclusions, pyramid-title consistency, source locators/provenance,
and honest abstention. Named hard gates reject the synthetic paper's mixed- or
process-noise, 30%, long-time, and statistical overclaims, as well as missing
I/O formats, invented unreported settings, title drift, and shallow structure.
Semantic marker groups and negation handling include English and Chinese
equivalents. The retrieval title is not matched to a gold sentence: it must
follow the candidate's own executive-summary formula and preserve the rubric's
applicability and conclusion semantics.
An I/O node may use an explicit `unreported`/`未报告` format only when
`workflow.missing_information` names that node (by ID, description, or semantic
type) and identifies the format gap; empty, generic, or unbound placeholders
still fail the hard gate.
Canonical-title provenance is read from `source_binding` and checked against the
source H1. Locator validity is derived from locator tokens printed by the source,
while the rubric's critical-locator coverage remains a separate requirement.
Explicit setting and stopping gaps may be owned by either workflow or algorithm
missing-information fields.

```bash
python evals/learn-from-papers/understanding_evaluator.py \
  --candidate /tmp/paper-understanding-v1.json \
  --rubric evals/learn-from-papers/understanding_rubric.json \
  --source evals/learn-from-papers/fixtures/synthetic_wsr_paper.md
```

`overall.passed` requires both `schema_validation.passed` and
`semantic_evaluation.passed`. Inspect the semantic dimensions and hard gates;
do not treat the aggregate score as a substitute for those diagnostics.
