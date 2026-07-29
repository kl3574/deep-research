# Real-world forward test: sparse dynamics identification and calibration

Date: 2026-07-29

Coverage: decision-oriented targeted investigation, not a systematic review

Skills under test: `deep-research`, `learn-from-papers`,
`curate-research-to-zotero`

## Research question

How should an agent investigate and choose methods for identifying sparse
dynamical structure and calibrating parameters when observation, noise,
excitation, and identifiability conditions vary?

The test required:

- a global-to-specific route map before selecting an algorithm;
- high-confidence orientation and decisive primary sources;
- legal acquisition and file verification;
- single-paper reconstruction with Chinese notes and LaTeX;
- explicit conflict, failure, and applicability analysis;
- a dry-run-first Zotero handoff.

## Bounded conclusion

The problem is not one algorithm-selection question. It separates into:

```text
observation and decision contract
-> structural discovery
-> fixed-structure parameter calibration
-> structural/practical identifiability
-> uncertainty and out-of-condition validation
```

Direct SINDy is one conditional branch: states are nearly fully observed,
derivatives are reliable, the true dynamics are sparse in the chosen
coordinates/library, and experiments sufficiently distinguish candidate terms.
Weak/integral methods address derivative-noise failure but do not remove
library completeness, excitation, observability, or errors-in-variables
concerns. Once a support is selected, physical calibration should normally be
rerun with the support fixed, the original observation/noise model, shared
parameter constraints, and uncertainty analysis.

## Route map

| Observation/problem contract | Primary route | Main gate |
| --- | --- | --- |
| Full-state deterministic trajectories, reliable derivatives | Direct SINDy/sparse regression | Library fit, excitation, column dependence, derivative quality |
| Full-state trajectories with substantial measurement noise | Weak or integral sparse identification | Window/test-function choice, quadrature, state-side EIV |
| Implicit or rational equations | Implicit/parallel-implicit routes | Candidate left-hand sides and library adequacy |
| Known structure, unknown parameters | Likelihood/least-squares/Bayesian calibration | Structural identifiability before optimization |
| Partial observations | Observability/state reconstruction plus discovery | Hidden-state non-uniqueness and coordinate meaning |
| Process noise is part of the dynamics | Sparse SDE drift/diffusion discovery | Separating process from measurement noise |
| Closed-loop input | Controlled identification with independent excitation | Separating input effects from state feedback |

## Consequential claims

| Claim | Evidence class | Bounded finding |
| --- | --- | --- |
| Sparse discovery is relative to coordinates and a candidate library | Primary method paper plus internal counterexamples | “Equation discovery” is not prior-free |
| Correct support does not imply accurate coefficients | Numerical examples in the SINDy paper | Some reported coefficients remain materially biased under noisy differentiation |
| Good derivative fit does not imply correct long-time dynamics | Internal failure cases | Rollout, stability, attractor, and invariant-statistic checks are separate |
| Off-attractor or multi-condition data can be decisive | Internal flow example and system-identification principles | Repeated data from one manifold may not distinguish mechanisms |
| Structural parameter identifiability is not sparse-support uniqueness or observability | Identifiability literature plus problem decomposition | Each requires a separate gate |
| FIM is a local diagnostic, not a proof of global or structural identifiability | Identifiability/profile-likelihood literature | Use profile or posterior checks when nonlinearity matters |
| AIC/BIC ranks generated candidates under assumptions | Model-selection paper and independent comparison | It cannot prove the true structure is present |
| Process and measurement noise imply different targets | SDE discovery literature | Do not force both into one residual-noise model |

## Corpus and file evidence

Ten legally accessible papers were acquired from publishers, societies,
recognized repositories, or author preprints. The corpus contains no
metadata-only records.

- Count: 10 PDF files
- Total size: 27,298,540 bytes
- Validation: all have a PDF signature, are unencrypted, and return successful
  `pdftotext` extraction
- Manifest:
  `~/.local/share/deep-research/sparse-dynamics-2026-07-29/manifest.json`
- PDF directory:
  `~/.local/share/deep-research/sparse-dynamics-2026-07-29/pdfs`

The public repository does not contain the PDFs. Canonical identity, inspected
version, download provenance, access basis, size, hash, page count, and text
extraction status are separated in the external manifest.

## Single-paper reconstruction finding

The foundational SINDy paper was reconstructed from a 44-page local
main-text-plus-supplement file. The reconstruction identified:

- known control parameters in the parameterized examples are input variables,
  not latent parameters inferred from state-only data;
- correct term support can coexist with appreciable coefficient bias;
- incorrect coordinates or missing functions can produce a compact but
  physically wrong model;
- transient/off-manifold data determine whether a full mechanism can be
  distinguished from an attractor-local closure;
- the supplement's Hopf Eq. (27) and Table 13 disagree on cross-term signs,
  which remains explicitly unresolved.

This forward test motivated a dedicated
`support -> coefficient -> physical parameter -> uncertainty` adapter,
main/supplement dual locators, formula/table/figure consistency checks, offline
source-status labels, and complete-read accounting.

## Additional reconstruction stress tests

Three route-critical papers were then independently reconstructed and projected
to schema-9 Chinese notes with LaTeX:

- Weak SINDy: 22/22 pages, 13 claims, and 6 display equations. Its covariance
  is a leading-order heuristic, the numerical threshold uses the true minimum
  nonzero coefficient, and a coefficient error of `0.008` coexists with a
  trajectory error of `0.56` in the Van der Pol example.
- WENDy: 36/36 pages, 19 claims, and 15 display equations. The paper's
  Eq. (15) covariance uses an OLS mapping while Algorithm 2 computes WLS/IRLS;
  the separate rank conditions do not guarantee full rank of the composed
  weak design; nominal intervals were not checked by empirical coverage.
- Parameter identifiability tutorial: 27/27 pages, 14 claims, and 7 display
  equations. The steady BVP depends only on two combinations of three
  parameters, and its reported “95% prediction interval” combines a 95%
  parameter set with conditional 5%--95% quantiles rather than a calibrated
  central 95% predictive interval.

These tests added direct composed-operator rank checks and an
estimator/covariance/interval consistency gate. They also confirmed that the
canonical publication record and the file actually read must be stored as
separate version facts.

## Zotero acceptance evidence

Three new parent/PDF/note bundles were imported one at a time into the confirmed
group collection
`PRIVATE_ZOTERO_TARGET -> PRIVATE_ZOTERO_TARGET -> PRIVATE_ZOTERO_TARGET -> PRIVATE_ZOTERO_TARGET`
(`TEST0001`). Readback verified:

- 3/3 parent DOI and collection memberships;
- 3/3 schema-9 Chinese child notes by normalized HTML equality;
- 3/3 local Zotero PDF copies by exact source/stored SHA-256 equality;
- zero duplicate DOI records in the pre-write checks.

The existing-note migration is a separate outcome. Twenty-eight existing child
notes passed schema-9 staging and live version/content/parent preflight; one
paper in the collection had no existing note. Only the SINDy note was
scientifically reconstructed in full, while the other 27 migrations preserve
the earlier content inside a new audited structure. Zotero 9.0.6 did not
advertise the HTTP local-write server ID, but its official Desktop **Run
JavaScript** surface provided a no-key route. A manifest-bound dry-run verified
28/28 exact notes, parents, versions, backups, hashes, collection membership,
and the selected target before a single Zotero database transaction updated
all 28.

Automatic sync stayed enabled. The runner waited for any active sync, acquired
Zotero's in-memory indefinite sync barrier only for the transaction and
readback, and released it in `finally`; the preference was `true` before and
after. Independent local-API readback found 28/28 advanced item versions,
correct parents and collection membership, and valid schema-9 notes. Twenty-
seven notes were byte-exact. Zotero normalized the SINDy table DOM and
whitespace, changing its stored hash, but all 217 text chunks, 13 headings, 15
table rows/cells, four LaTeX blocks, links, images, and schema validation were
equal. The original byte-only app report therefore remains as a transparent
false-positive failure record, paired with
`post_write_audit.json` under
`~/.local/share/deep-research/zotero-private-staging`.

After those writes, the hardened manifest-v2 stager was exercised again
against the then-current collection without writing Zotero: 33/33 parents were
enumerated, 32 each had exactly one child note and one explicitly bound PDF, one had
no existing note, and zero had multiple notes or ambiguous PDFs. The
independent local HTTP contract check matched all 33 parent, note, attachment,
content-type, link-mode, and collection snapshots. The final apply runner was
generated and syntax-checked but was not applied a second time; its new
inventory guards were executed with mutation fixtures, while the DOM
projection, sync watchdog, and transaction-outcome classifier were executed in
browser/Node harnesses. The full Python suite passed 117 tests.

## Skill defects observed and changes made

| Observation | Iteration |
| --- | --- |
| “Decisive source,” “atomic claim,” and “search round” were ambiguous | Added operational definitions |
| Missing companion skill had no fallback | Added labelled paper-card/ledger fallback without reconstruction overclaim |
| Canonical Version of Record and actually read copy could be conflated | Added explicit canonical/read-version pairing |
| Author/team overlap could inflate confidence | Added overlap fields for authors, data, code, and underlying studies |
| Theorem, synthetic benchmark, real experiment, review, docs, and runtime evidence were mixed | Added evidence-class separation |
| Structural identifiability, sparse-support uniqueness, and observability were conflated | Added a three-question terminology guard |
| Exact software version was requested even when behavior was not decisive | Made exact-version tracing conditional on decision relevance |
| Markdown note handoff disagreed with the HTML importer | Separated canonical Markdown and Zotero HTML projections |
| Note validation checked only UTF-8 and hashes | Added schema-9 section, Chinese, LaTeX, claim-table, locator, reconstruction-log, and provenance validation |
| Existing-note updates could be mistaken for Connector imports | Added backup- and version-guarded migration staging; duplicate-parent workarounds are forbidden |
| A paper's uncertainty formula can target a different estimator than its algorithm | Added an estimator/UQ consistency gate and direct derivation of the implemented estimator map |
| Separately full-rank factors were treated as sufficient for an identifiable composed regression | Added direct rank/conditioning checks for the composed operator and explicit equivalence-class tests |
| Nominal confidence, conditional quantile, and prediction levels were conflated | Added interval-type separation, quantile recomputation, and empirical-coverage checks |
| Existing-note capability probing used `OPTIONS` for a stateful authorization route | Deferred local authorization to approved apply mode, keyed support on the runtime server ID, and added local version-guarded PATCH/readback tests |
| Web-route dry-run treated key presence as sufficient | Added `/keys/current` group-write verification and full remote note/parent/hash/version preflight before any mutation |
| HTTP write capability was mistaken for the only direct-App route | Added a manifest-bound Zotero Desktop Run JavaScript dry-run and single-transaction updater |
| The user required automatic sync to remain enabled | Added an in-memory sync barrier that preserves the preference, waits for active sync, and always releases in `finally` |
| Byte-only readback rejected Zotero's equivalent table/whitespace normalization | Added byte-exact-or-semantic readback with text, headings, tables, LaTeX, link, and image projections |
| Compact Zotero `<br><strong>…` metadata caused a false SHA validation error | Made metadata validation treat HTML tags as semantic separators and added a regression fixture |
| The stager emitted too little target identity for the Desktop renderer | Bound staging to the selected local library/collection ID plus the keyed group collection hierarchy and complete path |
| Reusing a staging directory could overwrite approved backups or a prior manifest | Added reserved-directory checks and exclusive artifact/manifest creation; reruns require a new staging directory |
| A custom Desktop report path could alias the manifest, staged HTML, PDF, or template | Added resolved-path collision rejection before runner generation |
| A post-commit Zotero callback error could be mislabeled as rollback | Added an `onCommit` marker plus all-note old/new state inspection and an explicit unknown outcome |
| Transaction-start scope checks covered notes but not target/path or parent collection membership | Re-resolved the target and reloaded every parent/collection inside the transaction before the first save |
| Clearing Zotero's sync timeout could cancel a pending automatic sync or strand the barrier on error | Left existing timers intact and retained only the always-released in-memory barrier |
| The renderer trusted stale manifest validation metadata and silently filtered ambiguous entries | Re-ran the schema-9 validator and file hashes at render time; invalid/multiple-note states now block apply |
| Connector metadata could not prove local collection ID ↔ API group/key identity | Made Desktop the preferred exact-binding route; HTTP/Web apply now requires a separately verified and explicitly confirmed group/key |
| HTTP/Web `204` followed by failed readback was reported as if nothing had changed | Added accepted-but-unverified exceptions and partial-write reports that name the current note and backup |
| Parent-only inventory missed a newly added second child note between staging and apply | Upgraded to manifest v2 with complete parent/note/attachment snapshots, re-enumerated before apply and at Desktop transaction start |
| Desktop and HTTP fallback interpreted the same v1 manifest with different gates | Unified both on v2, live schema validation, PDF magic/hash binding, and explicit rejection of v1 |
| The first of multiple PDF children was silently treated as the full text | Multiple PDFs now block unless a reviewed parent-to-attachment map selects one; attachment parent, type, link mode, file magic, and hash are bound |
| An arbitrary 64-hex token could satisfy the full-text hash check | Bound exactly one Chinese `全文SHA-256` field to the approved PDF hash and added adversarial fixtures |
| Fixed-size item queries could silently prove only a collection prefix | Added advancing pagination and fail-closed duplicate/malformed-page checks |
| A Zotero attachment could be redirected while an old PDF path still retained the approved bytes | Bound the current Desktop attachment path and local `/file/view/url` to the manifest path, then rechecked it immediately before mutation |
| Web fallback could miss an unsynchronized local edit or local-only child change | Rechecked both local and remote inventories for every Web mutation and made the fresh local note version/hash the last pre-request gate |
| Python's HTML stack treated `<br>` as a container and could miss a trailing second root | Added void-element and matched-stack handling, exact one-root enforcement, and rejection of active elements, event handlers, and control-obfuscated active URLs |
| A timeout or HTTP 5xx left mutation outcome ambiguous | Classified transport/5xx outcomes by verified readback and reported an explicit unknown state when readback could not decide |
| Same-version new content could be misclassified as a committed Desktop write | Required every committed readback and transaction-outcome classification to advance beyond the old item version |
| A mistyped curated-override note key silently fell back to a generic wrapper | Validated every override key/path and rejected any override not consumed by exactly one eligible live note |
| Deleted objects or an unavailable PDF could survive into a half-bound staging manifest | Rejected deleted parents/children and made a readable local PDF with magic bytes, path, attachment identity, and hash mandatory |
| A reusable or group-writable staging tree exposed path-alias and replacement risk | Required a current-user, non-group/other-writable fresh root; reserved directories and files are exclusively created with no-follow leaf writes |
| The three skill entry files carried too much always-loaded instruction text | Kept hard gates in each entry, moved detail to selective references, and reduced every static invocation estimate below 900 tokens |

## Post-iteration efficiency audit

`plugin-eval` was run against the committed baseline and the revised working
tree with the same local evaluator:

| Skill | Baseline trigger / invoke | Revised trigger / invoke | Baseline -> revised score |
| --- | ---: | ---: | ---: |
| `deep-research` | 127 / 2540 | 90 / 896 | 67 D -> 81 C |
| `learn-from-papers` | 119 / 2665 | 78 / 890 | 67 D -> 81 C |
| `curate-research-to-zotero` | 125 / 1975 | 90 / 891 | 58 D -> 77 C |

These are static estimates, not observed model-token measurements. The
remaining grade penalty statically sums every reference, script, and test as
“deferred” even though the skills load them selectively. Its Python-complexity
heuristic also seeds each file's maximum from the decision count of the whole
file, so the reported `395` is not a function-level cyclomatic-complexity
measurement. Safety references, provenance logic, and tests were retained
rather than removed to improve that score.

## Stopping and limits

The targeted investigation stopped after two bounded rounds added no new
decision-relevant top-level route. It did not establish exhaustive recall.
Most method evidence is based on synthetic or author-team benchmarks, and route
performance must be retested on the target observation/noise contract.

The highest-information next action for a concrete project is not another
generic algorithm paper. It is an audit of measured states, inputs, sampling,
replicates, initial conditions, process-versus-measurement noise, candidate
physics, and the intended prediction or parameter decision.
