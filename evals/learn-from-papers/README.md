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
