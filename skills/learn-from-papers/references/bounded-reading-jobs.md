# Bounded paper-reading jobs

Use this when one selected paper or a separable subquestion can be read in
parallel with other useful work. A short direct lookup needs no worker. Keep
multi-paper synthesis in `$deep-research`; a reading job stays within one paper
lineage, including identified supplements and corrections.

## Brief before dispatch

Give the worker enough context to avoid rediscovery or uncontrolled expansion:

- The exact question, required subquestions, intended use, and exclusions.
- The chosen `map`, `evidence`, or `reconstruction` route and stop conditions.
- Canonical paper identity, version/date, access level, and supplied source
  paths or explicit acquisition route; include existing hashes and bundle or
  dossier references when available.
- Which components or source regions matter, any known conflicts, and which
  unresolved questions must remain visible.
- A separate work directory, permitted reads/actions, expected artifacts,
  and the requested output location. Do not overwrite finalized owner artifacts.

## Read from the owning source

Use the selected full text, supplement, or correction for paper claims; keep
abstract-only and metadata-only findings at their actual access level. Follow a
secondary description back to the source that owns the statement. If that source
cannot be inspected, record the gap instead of promoting the description to
full-text evidence.

For author code/data, retain the repository commit or dataset version and a
file/line or record locator. These are separately cited context, not substitutes
for a paper span in `PaperSourceBundle/v1`. Preserve original and normalized
source identities and lineage when OCR derivatives are involved.

Complete the existing route-specific source, dossier, understanding, and
verification work. Save proposed findings and drafts in the job directory; a
worker's confident answer, generated digest, or brief is not an attestation.

## Return and accept

Lead with the bounded answer. For each required question, cite the source version
and exact page/section/object locator, distinguish source statements from agent
inferences, and retain conditions, conflicts, and unanswered or `not_tested`
states. Link the supporting artifacts and report actual execution/check state.

The owner checks returned source/hash bindings, reopens the cited regions and
necessary context, and resolves material semantic or scope mismatches before
using the result. This targeted acceptance check does not require a second
complete read and does not become independent verification merely because a
worker was used. Preserve the existing attestation and governance boundaries.

If a readable note is requested, save one concise Markdown view where the
project already keeps such notes, using [knowledge-note.md](knowledge-note.md).
Keep job execution metadata in sidecars. The note is a view of the validated
reading artifacts; it cannot replace `PaperSourceBundle/v1`,
`PaperReadingDossier/v1`, `PaperUnderstanding/v1`, or a required
`PaperReadingReportSet/v2` projection. A `map` or diagnostic result stays
nondecisive and cannot be relabeled Tier A or used to bypass machine-handoff
requirements in [contracts.md](contracts.md).
