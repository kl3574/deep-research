# Research decomposition

Use this reference when the question is unfamiliar, spans several technical routes, or risks mixing incomparable evidence.

## Contents

- [Choose the research mode](#choose-the-research-mode)
- [Global map](#global-map)
- [Dimension-separated matrix](#dimension-separated-matrix)
- [Technical-route map](#technical-route-map)
- [Bottleneck ranking](#bottleneck-ranking)
- [Iterative search plan](#iterative-search-plan)
- [Identification terminology guard](#identification-terminology-guard)

## Choose the research mode

| Mode | Intended coverage | Required disclosure |
| --- | --- | --- |
| Targeted investigation | Decision-relevant representative evidence | Queries/routes used, what was omitted, pragmatic stop |
| Evidence map or scoping review | Concepts, evidence distribution, and gaps | Protocol/search/screening appropriate to the field |
| Rapid review | Bounded review with explicit shortcuts | Protocol, shortcuts, likely bias, reproducible search trail |
| Systematic review | Prespecified high-recall identification and synthesis | Field-appropriate protocol, screening trail, appraisal, and reporting |

Speed does not define the mode; method and coverage do.

## Global map

Before deep retrieval, create:

```text
decision
├── vocabulary and disputed definitions
├── object/population and scope
├── mechanisms or theories
├── method/technical-route families
├── evidence and validation traditions
├── maturity/timeline/version map
├── trade-offs and failure boundaries
└── implementation and operational artifacts
```

Start with several diverse seeds. A review or textbook can orient the map but must not silently become evidence for every leaf.

## Dimension-separated matrix

Use dimensions that isolate different reasons conclusions may diverge:

| Dimension | Questions |
| --- | --- |
| Object/scope | What object, population, task, regime, or outcome is addressed? |
| Mechanism | What causal, mathematical, or operational link is proposed? |
| Route | Which method family and concrete technique are used? |
| Evidence | How was the claim validated, with what uncertainty and maturity? |
| Context | Which time, version, platform, configuration, or institution applies? |
| Boundary | Which assumption, trade-off, failure, or exclusion limits it? |
| Artifact | Which data, code, standard, manual, model, or runtime realizes it? |

Treat independence between dimensions as a testable proposition. If one dimension affects another, represent the interaction explicitly.

## Technical-route map

For each route, fill:

```text
target problem and success criterion
mechanism or design principle
required assumptions and prerequisites
inputs -> transformation -> outputs
representative implementations and versions
validation method and strongest evidence
resource, safety, and operational constraints
known failures and counterexamples
conditions favoring or excluding this route
unresolved bottleneck
```

Compare routes only after normalizing target, constraints, metric, dataset/environment, and maturity. Avoid a single weighted score when trade-offs are decision-specific.

## Bottleneck ranking

Prioritize a gap when it:

- changes the decision;
- blocks several downstream claims;
- has high uncertainty or conflict;
- can be resolved with a reachable high-fit source or test;
- is expensive to discover only after implementation.

A visually broad branch with low decision impact should not displace a narrow dependency that controls the outcome.

## Iterative search plan

For each round record:

| Round | Claim/gap | Source/index or seed | Exact query/path | Filters/version/date | Screened | Included | Exclusion reason | New information |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

Use database/search discovery, backward references, forward citations, related concepts, exact artifact/version tracing, and targeted contradiction queries as complementary routes. Search snippets only point to candidate sources.

For a non-systematic task, two consecutive rounds with no new decision-relevant concept, route, conflict, or evidence can support a pragmatic stop. It cannot prove recall completeness.

A round is auditable only when it has one recorded gap, one coherent route or
bounded query set, screened candidates, exclusions, and a new-information
result. Several parallel queries for the same gap and route are one round;
backward citation chasing, forward citation chasing, and correction searching
are separate rounds because their recall mechanisms differ.

## Identification terminology guard

Do not collapse these questions:

| Question | Object | Typical gate |
| --- | --- | --- |
| Structural parameter identifiability | Parameters of a fixed model under an idealized input/observation contract | Whether distinct parameter values can produce identical ideal outputs |
| Sparse-support uniqueness | Active terms or reactions inside a chosen candidate library on the available experiment design | Library completeness, rank/coherence, excitation, regularization, and finite-sample stability |
| State observability | Hidden state reconstruction from measured outputs and known inputs | Whether distinct states can produce indistinguishable outputs |

They interact, but success in one does not prove the other two. State which
contract changes—new outputs, inputs, initial conditions, or regimes—when a new
experiment appears to repair an identifiability problem.
