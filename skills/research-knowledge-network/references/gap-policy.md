# Gap policy

## Gap categories

1. **explicit**
   - Declared externally (user/analyst request or run contract requirement).
2. **deterministic structural**
   - Derived from explicit structure/coverage checks.
3. **implicit_candidate**
   - Derived as auditable candidates, not novelty claims.
   - Must include all fields:
     - `grounds`
     - `warrant`
     - `backing`
     - `qualifier`
     - `defeaters`
     - `search_test`

## Derivation requirements

`derive-gaps` must detect at minimum:

- unsupported high-impact claims (no decisive evidence)
- claims with only a single independent source group
- open conflicts between evidence polarities
- missing promised dimensions/benchmark profiles from init contract
- topological isolates (must be `implicit_candidate` only)

## Novelty boundary

`implicit_candidate` gaps are for coverage planning and must **never** set novelty as true.
The command must reject novelty assertions in implicit candidates.

## Completion gate

`validate` and `status` report blockers.
Completion is allowed only when:

- no open high-impact gaps
- no open conflicts
- no unmet promised coverage dimensions/benchmarks
