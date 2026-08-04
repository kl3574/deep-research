# Algorithm benchmark profile

Use `BenchmarkProfile/v1` for every toy model or real benchmark used to compare
identification, calibration, uncertainty, or experimental-design algorithms.
The profile prevents a familiar model name from hiding incompatible equations,
parameters, observations, noise, or splits.

## Contract

```json
{
  "schema": "BenchmarkProfile/v1",
  "benchmark_id": "BENCH-001",
  "name": "Lotka-Volterra protocol A",
  "task_modes": ["support_recovery", "fixed_support_calibration"],
  "model": {
    "equations_or_model_ref": "claim:MODEL-001",
    "candidate_library": "explicit library or source locator",
    "ground_truth": "true support and parameter reference",
    "parameters": "values or exact source locator",
    "initial_conditions": "values/distribution or exact source locator",
    "inputs_or_perturbations": "none or explicit protocol"
  },
  "observation_protocol": {
    "observed_states": "full or named partial observation",
    "inputs_or_perturbations": "known inputs and intervention schedule",
    "noise": "distribution, scale, correlation, and process/measurement role",
    "sampling": "time grid, horizon, and replicate schedule",
    "trajectories": "number and grouping by initial condition/input"
  },
  "evaluation": {
    "split": "trajectory-level train/validation/test rule",
    "metrics": ["support TP/FP/FN", "parameter error", "forward error"],
    "equivalence_rule": "exact support or declared dynamical equivalence"
  },
  "failure_boundaries": [
    "candidate library omits the true term",
    "sampling does not resolve the fastest timescale"
  ],
  "evidence": {
    "source_claim_refs": ["claim:MODEL-001"],
    "exact_locators": ["source:SRC-001 | PDF p.4 | Eq. (7)"]
  }
}
```

## Required interpretation

- Separate support discovery from fixed-support parameter calibration.
- State whether all states are observed and whether true initial conditions are
  supplied.
- Preserve the exact parameterization; model names alone are not protocols.
- Split held-out evaluation by complete trajectory, initial condition, input, or
  perturbation, not by randomly shuffled time points.
- For chaotic systems, distinguish support recovery and short-horizon prediction
  from impossible long-horizon pointwise agreement.
- For chemical reaction networks, state whether evaluation is over regression
  support, stoichiometric reactions, or a declared dynamical-equivalence class.
- A real-data example without ground truth cannot report exact support accuracy.

Each benchmark card must cite claim IDs and exact full-text locators. Orientation
sources and uncited parameter conventions are insufficient.
