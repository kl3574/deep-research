# Evidence-first retrospective method

## Unit of analysis

An incident is one preventable failure mode at one owner seam. It is not every
failed command, every error message, or every rejected draft. Merge repeated
symptoms when the same gate and change would prevent them; split incidents when
they require different owners or tests.

Keep four layers separate:

1. `observation`: what the retained evidence directly shows;
2. `cause`: the smallest mechanism reproduced or otherwise justified;
3. `change`: what interface or implementation should change;
4. `verification`: which red, green, forward, and adversarial tests passed.

A final successful artifact does not erase earlier escapes. A rejection that
prevented an incorrect mutation is evidence that fail-closed governance worked,
even when the same rejection exposed an expensive late seam.

## Earliest detectable gate

Ask at each prior stage: did this stage already possess both representations or
facts required to reject the incident mechanically? The earliest such stage is
the prevention point. Do not move a semantic decision to an orchestrator that
lacks the owner evidence merely to reduce escape distance.

Examples:

- a locator emitted by one owner but rejected by the next belongs at their typed
  contract seam;
- an invalid PDF detected after import belongs in acquisition/import preflight;
- a false public-redaction result belongs in the publisher's projection tests;
- a paper that only qualifies a claim remains an appraisal decision, not a
  generic pipeline check;
- a disconnected browser bridge is normally a one-off environment incident
  unless recovery logic repeatedly mishandles it.

## Generalized versus one-off

Treat an incident as generalized when at least one of these is true:

- it recurred with independent inputs;
- a minimal reproducer crosses the public owner interface;
- two real adapters disagree on the same shared representation;
- the same failure class can corrupt authority, privacy, or irreversible state;
- a withheld forward case fails for the same mechanism.

Environment availability, one corrupt legacy object, or a single provider limit
is not enough to create a skill. Improve diagnostics or recovery only when the
workflow response itself is the recurring problem.

## Change placement

Use the deletion test. If deleting the proposed module spreads the same
validation logic across two or more real callers, a shared module may earn its
interface. If deletion merely removes a wrapper around one owner, keep the fix
inside that owner.

New skills must have:

- a distinct user trigger;
- inputs and outputs not already owned elsewhere;
- explicit non-goals;
- an independent acceptance surface;
- enough behavior behind a small interface to justify discovery cost.

## Evaluation ladder

Use four levels, stopping fail-closed when one fails:

1. **Reproduction** — exact old failure shape is red before the fix.
2. **Owner regression** — public owner interface is green after the fix and
   adjacent security/authority controls remain green.
3. **Forward case** — a different input with the same mechanism passes or is
   correctly rejected without special-case text matching.
4. **Release/install proof** — fixed commit, CI, immutable tag/release, staged
   byte comparison, backup-preserving installation, loader/doctor verification.

For web-enabled research-agent evaluation, keep an offline or frozen-corpus lane
and an adversarial live lane. Search-enabled agents can discover benchmark answer
keys or leaked examples; a high static benchmark score alone is not reliable
evidence of research quality.
