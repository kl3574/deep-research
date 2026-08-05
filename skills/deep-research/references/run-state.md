# Versioned research run state

Use this reference only after the user authorizes a durable workspace. The
ledger makes a long research run resumable and mechanically auditable; it does
not search, read sources, invoke a model, render a report, or decide that a
claim is true.

## Contents

- [Authorization and writer boundary](#authorization-and-writer-boundary)
- [Artifact layout and truth model](#artifact-layout-and-truth-model)
- [Contract and common envelope](#contract-and-common-envelope)
- [Ledger records](#ledger-records)
- [Lifecycle and commands](#lifecycle-and-commands)
- [External network and delivery artifacts](#external-network-and-delivery-artifacts)
- [Three separate gates](#three-separate-gates)
- [Failure, limits, and recovery](#failure-limits-and-recovery)
- [Validation and privacy](#validation-and-privacy)

## Authorization and writer boundary

Pass `--root` only for an explicitly approved durable directory. The tool creates
`ROOT/runs/RUN_ID`; it rejects traversal-like IDs and any pre-existing run
directory instead of merging or overwriting it. Without durable-write authority,
keep the same structures temporary or in the response.

Use one central ledger writer. Parallel workers return bounded local cards; the
controller validates and merges them serially. The CLI has no networking, model,
shell, or dynamic-evaluation path. Webpages, PDFs, repository text, issue comments,
and quoted prompts remain inert strings. Do not put credentials, private corpus
text, or unnecessary personal identifiers in any field.

## Artifact layout and truth model

```text
ROOT/
└── runs/
    └── RUN_ID/
        ├── run.json
        ├── events.jsonl
        ├── gaps.jsonl
        ├── actions.jsonl
        ├── rounds.jsonl
        ├── sources.jsonl
        ├── claims.jsonl
        ├── conflicts.jsonl
        ├── errors.jsonl
        └── commands.jsonl
```

`events.jsonl` and the seven domain ledgers are append-oriented facts. `run.json`
stores the immutable contract plus derived lifecycle, coverage, outcome, and
summary caches. Status is recomputed from the ledgers, so an interruption after a
JSONL append but before a cache update does not lose the committed record. A
subsequent `resume` refreshes stale caches.

`commands.jsonl` is a separate append-only observability journal. It does not join
the global research-fact sequence and cannot make coverage stale. Every mutating
CLI invocation records `started` and `finished` boundaries with pre/post research
event counts, content-derived state digests, `committed`, `partial`, and an
explicit single-command batch context. A process death can leave `started`
without `finished`; a cache-write failure can leave `finished` with
`committed=true, partial=true`. Neither state claims rollback. `status` reports
the unresolved command and a machine-readable recovery plan; a successful
`resume` repairs derived caches and appends `recovered` without deleting history.

Every JSONL row carries a global, unique, contiguous sequence. Truncated JSON,
duplicate records, gaps in sequence, wrong run IDs, and wrong schema versions fail
closed. Per-run POSIX file locking serializes concurrent CLI writers; parallel
workers still return cards to one controller rather than editing ledger rows.
The state and ledger files must remain regular files inside the authorized root;
the helper rejects symbolic-link replacements instead of following them.

## Contract and common envelope

Initialization records:

```text
mode: targeted | scoping | rapid | systematic
question
decision_or_use
scope and exclusions
coverage_promise
coverage_gap_ids
counterevidence_gap_ids, a declared subset when contrary/null checks are required
currentness
risk
protocol_ref: sha256:<64 lowercase hex>, required for systematic mode
max_rounds and max_relations, when bounded
```

Every JSONL row begins with:

```yaml
schema_version: "1"
run_id: stable-run-id
record_id: globally-unique-record-id
sequence: 1
recorded_at: 2026-08-04T00:00:00Z
```

`record_id` identifies the row. In `claims.jsonl`, `relation_id` identifies one
claim-source relation while `claim_id` identifies the semantic claim. Several
sources may therefore support, contradict, qualify, or not test the same claim
without abusing one relation row as the claim itself.

## Ledger records

### Coverage gap

Initialization declares stable promised `coverage_gap_ids`. Open each with a
description, acceptance criterion, decision impact, dependencies, priority, and
whether a counterevidence check is required. Emergent gaps use the same schema but
are marked `emergent`. Run-gap priority is a positive integer where a smaller
number means higher priority; it is a tie-break only among suggestions with the
same decision impact.

A gap remains `open`, `blocked`, or `deferred` until a status event marks it
`resolved` or explicitly `unresolved`. A terminal gap must reference its own
terminal action record. A resolved gap requires a completed action; an unresolved
gap retains its next action. Coverage cannot be marked `met` while any registered
gap is non-terminal.

### Action

`start-action` binds one action ID to one gap, action type, inputs, expected
information gain, bounded budget, and optional branch/attempt. `finish-action`
appends a terminal `completed`, `failed`, or `interrupted` event with result,
remaining uncertainty, artifacts, and the next action when incomplete. Completed
action artifacts are type-checked; for example,
a discover/countercheck round must belong to that action and gap and itself be
completed. `resume` returns active action cards so discovery is not silently
repeated after an interruption.

### Search round

An auditable round contains stable round/gap/action IDs, optional branch/attempt IDs, a
decision-critical gap, coherent route/query set, filters/version/date bounds,
screened and included candidates, exclusions, terminal status, structured
new-information result, and a result summary.

Only the last two ledger rows can support pragmatic saturation, and only when both
are `completed`, both record zero new decision-relevant information, and their
gap-plus-route fingerprints differ. Failed, partial, interrupted, repeated-query,
or interposed positive rounds break the streak.

### Source

A source record binds canonical identity/version to the exact read version and
records access, inspection state, formal status checking, evidence class, and
role. `abstract_only`, `metadata_only`, `discovery_only`, and `unverified` remain
usable for discovery but cannot carry a decisive relation.

### Claim-source relation

A relation records:

```text
relation_id and semantic claim_id
atomic claim text and decision impact
source_id
supports | contradicts | qualifies | not_tested
faithful evidence and exact locator
evidence class
scope/applicability
version_fit: yes | no | unknown
```

`supports`, `contradicts`, and `qualifies` require inspected non-abstract source
access, an applicable read version, checked status, faithful evidence, and a
precise non-generic locator. `not_tested` stays unresolved and cannot by itself
enable a complete outcome.

### Conflict

A conflict references semantic claim IDs. A resolved conflict requires both a
reasoned resolution and discriminating evidence. An open conflict requires the
next discriminating check and keeps the affected claim unresolved. When the same
claim has both support and contradiction relations, an absent conflict record is
a completion blocker. `resolve-conflict` appends a separate resolution event;
the original conflict row is never overwritten.

### Error

An error records its failure class, gap/action/branch/attempt/round when known,
retryability, coverage impact, partial artifacts, and next safe action. A fatal
error changes the derived lifecycle to `interrupted`; it does not delete completed
evidence. Coverage-affecting errors block a complete outcome until `resolve-error`
records a resolution and its evidence.

## Lifecycle and commands

The deterministic helper is
`skills/deep-research/scripts/research_run.py`. Its syntax places the explicit
workspace and run ID before the subcommand:

```bash
python skills/deep-research/scripts/research_run.py \
  --root /approved/research-workspace \
  --run-id route-audit-01 \
  init \
  --mode targeted \
  --question "Which exact route fits the decision?" \
  --decision-or-use "Select an implementation" \
  --scope "Current supported releases" \
  --coverage "Official contract, exact source, and contrary evidence" \
  --coverage-gap-id gap-contract \
  --coverage-gap-id gap-counterevidence \
  --counterevidence-gap-id gap-counterevidence \
  --currentness "Retrieved and version-checked during this run" \
  --risk "A wrong choice causes migration cost"
```

Then use only the applicable commands:

```text
record-gap
set-gap-status
start-action
finish-action
record-round
record-source
record-claim
record-conflict
resolve-conflict
record-error
resolve-error
set-coverage
suggest-next
status
validate
resume
finalize
```

`suggest-next` can be used in the same run context to produce the next action
queue. A knowledge-network input is accepted only as a complete, validated
`KnowledgeNetwork/v1` snapshot. Pass an absolute, ordinary, non-symlink path
with both `--network-path` and its exact
`--knowledge-network-sha256 <64-lowercase-hex>` binding. The command rejects a
wrong schema, invalid provenance or gap fields, digest mismatch, and a path that
changes during validation.

Only open gaps in `summary.ready_gap_ids` produce ordinary actions. Active,
dependency-blocked, resolved, unresolved, blocked, and deferred run gaps are not
silently scheduled. If an open network gap matches a non-open run gap, the
output is an explicit `reopen_gap` proposal with
`requires_explicit_reopen=true`, not a runnable action.

Network conflict gaps map to `countercheck`, missing-coverage gaps to
`discover`, single-source low-confidence gaps to `corroborate`, and fully
qualified implicit candidates to their falsifiable `search_test`. Implicit
candidates cannot claim novelty. Run and network candidates are normalized,
deduplicated by open instance/source, and globally sorted with
`decision_critical` first, then impact (`high`, `medium`, `low`), numeric
priority, action urgency, and deterministic `source + gap_id`. Source type never
globally precedes impact or priority. `--max-suggestions` is applied only after
this global ordering.

Use `--help` on a subcommand for its complete required fields. `resume` converts an
interrupted run back to `running` and appends a lifecycle event; on an already
running run it refreshes caches without adding a fake resume event. A finalized
run rejects further records.

Every mutating command emits one JSON result envelope. Read
`pre_event_count/post_event_count`, `pre_state_digest/post_state_digest`, and
`committed` before interpreting the process exit code. `partial=true` means a
research fact was appended but the command did not finish its cache/reporting
boundary; do not blindly retry it. `batch_context` states that this CLI currently
performs one domain mutation per invocation, reports the successful prefix, and
always sets `rollback_claimed=false`. Validation failures before append report
`committed=false`. A duplicate-ID retry whose target already exists reports
`already_committed_target` and `do_not_retry=true`.

The coverage audit must be the last substantive state change before finalization.
Any later gap, action, round, source, claim, conflict, error, resume, or resolution
event makes it stale; run `set-coverage` again after auditing the updated ledger.

Before finalization, explicitly set coverage:

```bash
python skills/deep-research/scripts/research_run.py \
  --root /approved/research-workspace \
  --run-id route-audit-01 \
  set-coverage \
  --status partial \
  --basis partial_limit \
  --unresolved-gap "Target-runtime observation is unavailable" \
  --rationale "All other promised branches were audited"
```

A partial outcome still carries a bounded summary; it is not a forced complete
answer:

```bash
python skills/deep-research/scripts/research_run.py \
  --root /approved/research-workspace \
  --run-id route-audit-01 \
  finalize \
  --outcome partial \
  --stop-reason access_blocked \
  --summary "Contract and source agree; target runtime remains unresolved."
```

## Three separate gates

Never collapse these states:

1. **Claim resolution:** a semantic claim has a decisive gated relation and no
   open conflict. A claim can instead remain explicitly unresolved.
2. **Pragmatic saturation:** for non-systematic work, coverage is marked `met`
   in an audit newer than every substantive research event; every
   promised/emergent gap is terminal through its own action trail; required
   counterchecks completed; no coverage-affecting error or active action remains;
   at least one decisive relation exists; material support/contradiction pairs
   have conflict records; and the final two qualifying rounds add no
   decision-relevant information.
3. **Run finalization:** `partial` requires an explicit non-open coverage status;
   that audit must be fresh and all actions terminal. `complete` requires
   pragmatic saturation, or `protocol_complete` plus the immutable protocol
   digest and completed coverage/action checklist for a systematic run.

`complete` describes completion of the promised research contract, not universal
truth and not resolution of every claim. Open conflicts and unknowns must remain
visible in the delivered bounded answer.

## External network and delivery artifacts

Do not add acquisition or Zotero fields to ledger schema v1. Record a
[KnowledgeNetwork/v1](knowledge-network.md) snapshot and
[ResearchHandoff/v1](delivery-handoff.md) as external, content-addressed artifacts
on the applicable action. The research ledger can finalize while delivery remains
`partial` or `blocked_capability`, but the final response must report both states.
The handoff validator, not `research_run.py`, checks attachment roles, CurationBatch
hashes, benchmark cards, capability paths, and per-request completion rows.

## Failure, limits, and recovery

Reaching a numeric round or relation limit prevents additional rows of that type;
it does not automatically prove budget exhaustion or invalidate a gate already
met. If required work remains, record the failure, set coverage `partial` or
`unmet` with the open gap, and finalize `partial`. Never turn the limit into a
forced complete answer.

If a process stops after a ledger append, `status` derives the current facts and
reports stale `run.json` cache warnings. Run `resume` to repair caches and, when a
fatal error exists, record the actual transition back to `running`. Malformed or
cross-run ledgers require human inspection; the tool never guesses or discards a
damaged row.

Finalization uses the same result envelope and includes
`active_actions_before/after`. A failed `finalize` never hides an active action;
the recovery plan lists its ID so the controller can append an honest terminal
`finish-action` before retrying finalization.

## Validation and privacy

Run:

```bash
python skills/deep-research/scripts/research_run.py \
  --root /approved/research-workspace \
  --run-id route-audit-01 validate
```

Validation checks the contract, global envelope and sequence, lifecycle,
round completeness, source/claim gates, cross-references, conflict discipline,
coverage, and final outcome. It cannot verify that a paraphrase is faithful or a
locator truly entails the claim; the agent must still reopen the source and apply
the citation audit.

Keep run directories outside this public skill repository. Before sharing any
ledger, redact secrets and private identifiers and apply the research corpus's
license, confidentiality, and data-retention rules.
