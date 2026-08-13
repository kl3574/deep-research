---
name: research-workflow-retrospective
description: Audit hash-pinned evidence from a completed, failed, or reworked research run to locate preventable seams and propose test-ready skill improvements. Use when the user asks for a post-run retrospective. Do not use to conduct research, mutate state, publish, or implement changes.
---

# Research Workflow Retrospective

Convert evidence from an actual research run into a deterministic improvement
review. Preserve the distinction between an observed incident, an architectural
inference, a proposed change, and a verified regression fix.

## Operating boundary

- Treat the inspected run and all owner artifacts as read-only.
- Do not browse, reinterpret paper evidence, approve an appraisal, mutate Zotero
  or a research network, publish a report, or alter a skill under this skill.
- A retrospective can recommend implementation. Apply that recommendation only
  under the owning skill or `$skill-creator`, with explicit write authority.
- Keep real run bundles and reviews in an authorized private workspace. Commit
  only synthetic fixtures and generalized lessons.
- Do not infer completion from a final report alone. Reopen the run state,
  terminal receipts, rejected attempts, independent reviews, and release/install
  evidence that control the claim being made.

Read [method.md](references/method.md) before classifying incidents and
[contracts.md](references/contracts.md) before producing a machine-readable
review. Read [agentic-research-design.md](references/agentic-research-design.md)
when comparing the workflow with current research-agent patterns.

## Workflow

### 1. Freeze the review question

Record the reviewed run, scope, stage order, decision/use, and the exact evidence
files. State whether the task is diagnosis only or includes later implementation,
testing, release, and installation. Do not silently broaden authority.

### 2. Reconstruct the actual trajectory

Build a timeline from state ledgers and immutable artifacts, not from the final
answer. Include failed attempts, reissues, handoff waits, independent rejections,
runtime fixes, dry runs, real runs, and publication/install proofs. Separate:

- scientific or domain uncertainty;
- owner-contract or representation seams;
- implementation bugs;
- workflow-state and recovery failures;
- coordination or observability costs;
- presentation and delivery failures;
- truly one-off environment incidents.

For every incident, record both `detected_stage` and the earliest stage where a
mechanical gate had enough information to reject it. The distance between them is
the escape distance; it is not a substitute for impact.

### 3. Place the seam

Prefer the narrowest owner that can prevent recurrence:

1. owner implementation/test when one module already owns both representations;
2. shared contract only when two real adapters need the same typed object;
3. orchestration/run-state contract for continuation, recovery, or progress;
4. a new narrow skill only when the responsibility has its own trigger, inputs,
   outputs, non-goals, and independent acceptance surface;
5. documentation or a local repair for non-recurring incidents.

Do not add a pass-through skill that merely restates other owners' checks. Do not
weaken independent review or raw-byte trust boundaries to save coordination time.

### 4. Compile the deterministic review

Create a private `ResearchWorkflowEvidenceBundle/v1`, then run:

```bash
python scripts/workflow_retrospective.py build \
  --bundle /private/workflow-evidence-bundle.v1.json \
  --expected-bundle-sha256 <64-lowercase-hex> \
  --output /private/research-workflow-review.v1.json

python scripts/workflow_retrospective.py validate \
  --bundle /private/workflow-evidence-bundle.v1.json \
  --review /private/research-workflow-review.v1.json \
  --expected-bundle-sha256 <64-lowercase-hex> \
  --expected-review-sha256 <64-lowercase-hex>
```

`build` first requires the caller's external raw bundle pin, then reopens every
regular non-symlink file, checks raw SHA-256, rejects
duplicate seams and credential-shaped content, derives escape distance, priority,
and implementation readiness, and writes a mode-0600 file without overwrite.
`validate` requires external raw pins for both bundle and review, reopens the
original bundle and all evidence, rebuilds the review, and requires exact
equality.

### 5. Turn findings into tests before implementation

Every generalized change needs at least one acceptance test and one negative or
adversarial test at the proposed seam. Prefer a red reproduction from the actual
failure shape, then a green owner-interface test. Add a withheld forward case so
the change is not fitted only to the original incident.

For research-agent changes, evaluate at least:

- instruction and source-boundary adherence;
- claim-to-source entailment and locator validity;
- coverage against a task-specific rubric;
- primary-source quality and counterevidence balance;
- deterministic or independently replayable artifacts;
- recovery from interruption and stale inputs;
- single-agent versus multi-agent routing cost;
- benchmark contamination or unintended solution paths.

### 6. Require independent closure

After implementation, use an independent reviewer to verify the exact candidate
tree, test receipts, public/privacy boundary, release tag, and installed manifest.
A passing unit suite does not prove a release or installation; a copied directory
does not prove one tagged, reproducible skill set is active.

## Completion contract

Return:

- the pinned review and its digest;
- incident counts by priority, owner, classification, and readiness;
- the highest-leverage seams and explicit non-goals;
- which recommendations were only proposed versus implemented and tested;
- forward-evaluation, release, and installation evidence when those actions were
  separately authorized;
- remaining blockers and whether they are scientific, operational, or one-off.

Never claim that the workflow is generally improved from one replay alone. Say
which incident classes and forward cases were actually exercised.
