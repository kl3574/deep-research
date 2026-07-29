# Paper-type adapters

Select the primary adapter and add any secondary adapter needed by a hybrid paper.

## Theoretical or mathematical

Extract:

- objects, domains, notation, and definitions;
- assumptions, including hidden regularity or identifiability conditions;
- theorem dependency graph;
- proof strategy and the non-routine step;
- equality, limiting, or singular cases;
- difference between a proved statement, heuristic, conjecture, and numerical illustration.

Reconstruct at least one central derivation or proof skeleton. Test whether the conclusion survives weakened assumptions. Do not replace an unavailable proof with a plausible one and attribute it to the authors.

## Empirical, experimental, or observational

Extract:

- research question and estimand;
- design, population, sampling, intervention/exposure, controls, and outcomes;
- preprocessing, exclusions, missing-data handling, and leakage risks;
- statistical model, uncertainty, multiplicity, and effect size;
- preregistration, robustness checks, negative results, and adverse outcomes;
- internal validity, external validity, and plausible confounding.

Keep association, prediction, and causation distinct. Report denominators and absolute quantities when the paper provides them.

## Method, algorithm, or system

Extract:

- input/output contract and intended operating regime;
- algorithm or architecture and key design choices;
- training or optimization objective;
- computational and data requirements;
- baselines, ablations, sensitivity, and failure cases;
- implementation details, code/data availability, and reproducibility gaps.

Translate prose into an executable or pseudocode-level pipeline only when supported. Mark every filled-in implementation detail as inference.

## Dynamical-system identification or parameter calibration

Keep four layers distinct:

$$
\text{support/structure}
\rightarrow
\text{regression coefficient}
\rightarrow
\text{physical parameter}
\rightarrow
\text{uncertainty}.
$$

Extract:

- state, input, output, hidden variables, coordinates, sampling, and experiment/trajectory units;
- whether structure is unknown, fixed, partially specified, or chosen from a candidate library;
- dictionary completeness, scaling, column dependence, persistent excitation, observability, and hidden-state assumptions;
- derivative measurement/estimation, integral or weak formulation, irregular sampling, and errors-in-variables;
- whether a parameter is known control input, unknown latent value, shared physical parameter, or reduced-coordinate coefficient;
- structural identifiability, sparse-support uniqueness, practical identifiability, and observability as separate claims;
- cross-equation constraints, regularization/threshold selection, support stability, and post-selection re-estimation;
- measurement noise, process noise, model discrepancy, uncertainty intervals/posteriors, and calibration objective;
- preprocessing, hyperparameters, seeds, solver tolerances, and missing reproduction-critical details.

For fixed-structure calibration, audit the composed inverse problem rather than
isolated factors:

- test whether the parameter-to-observation map is one-to-one, and exhibit an
  equivalence class or null direction when it is not;
- check the rank and conditioning of the actual composed design/operator; full
  rank of two factors separately does not imply full rank of their product;
- derive the estimator map from the implemented update and compare it with the
  paper's covariance formula (for example OLS, WLS, GLS, IRLS, profile, or
  posterior); do not attach an OLS sandwich to a different estimator without an
  explicit approximation argument;
- separate a parameter confidence set, a conditional observation interval, a
  prediction interval, and a posterior predictive interval; recompute the
  stated quantile level and look for empirical coverage rather than accepting a
  nominal label;
- cross-check noise scaling, parameter perturbation ranges, normalization, and
  sample-count conventions between equations, tables, captions, and code.

Validate dynamical claims at distinct levels:

1. derivative or weak residual;
2. short-horizon rollout on held-out trajectories;
3. new initial conditions, inputs, parameters, or operating regimes;
4. equilibria, stability, conservation, bifurcations, and limit cycles;
5. long-run attractor or invariant statistics when relevant;
6. support and parameter stability under data/preprocessing perturbations.

One level cannot substitute for all others. A correct support does not prove unbiased coefficients; a small residual does not prove correct long-term dynamics; a reduced-coordinate coefficient is not automatically a physical parameter.

Cross-check every central equation against coefficient tables, figures, captions, code/pseudocode, and examples. Record sign, normalization, coordinate, or notation conflicts as internal paper inconsistencies rather than silently choosing one.

## Dataset, benchmark, or resource

Extract:

- target construct and intended use;
- source population or corpus, collection process, licenses, and consent;
- annotation protocol and agreement;
- splits, contamination, leakage, and representativeness;
- metric definition and known blind spots;
- maintenance, versioning, and access conditions.

Do not equate leaderboard performance with general capability outside the benchmark's construct and distribution.

## Review, meta-analysis, or evidence synthesis

Extract:

- review question and protocol;
- databases, dates, queries, and supplementary search methods;
- inclusion/exclusion criteria and screening process;
- study-quality or risk-of-bias assessment;
- synthesis model, heterogeneity, publication bias, and sensitivity analyses;
- whether conclusions reflect primary evidence or review-author interpretation.

Do not inherit a review's characterization of a primary study when the exact primary claim is decision-critical; inspect the primary source.

## Position, perspective, or commentary

Extract:

- thesis and intended audience;
- premises and value judgments;
- evidence type used for each premise;
- strongest alternative position;
- recommendations and the assumptions needed for them to work.

Do not report an argumentative recommendation as an empirical finding.

## Mixed papers

Apply adapters per claim. A paper can provide a theorem, a software system, and an empirical benchmark; evaluate each contribution under its own evidence standard.
