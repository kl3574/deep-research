# Six-skill workflow routing evaluation

This evaluation checks the release-level orchestration boundaries shared by the
six research skills. It is intentionally smaller than the mutation-oriented
end-to-end tests under `research-knowledge-network`.

Covered cases:

1. Field-only research stays in `deep-research` and does not invent a network.
2. Existing Zotero material routes through inventory/read, paper learning, and
   then network ingestion and snapshotting.
3. An open-world gap routes from an exact network snapshot through
   `network-gap-discovery` to `ScholarDiscoveryRequestSet/v1` and documented API
   discovery.
4. Google Scholar is accepted only as `user_manual_export`; automatic execution
   is rejected by both the route evaluator and the production Scholar validator.
5. A new source must be curated, onboarded, and included in a fresh snapshot
   before it can support `NetworkPatchProposal/v2`.
6. Decisive evidence requires a passed, separately declared context attestation
   and verifier contexts, and `finalize-attestations` before consumption.
7. A v2 patch requires a typed plan and explicit
   `NetworkPatchAcceptance/v1` from external governance before apply.

The public-contract probes dynamically load the production Scholar request-set
validators, compile and adversarially tamper a Scholar query plan, and inspect
the production dossier and patch CLI gates. They make no network calls.

Run:

```bash
python -m unittest discover -s evals/research-workflow -p 'test_*.py'
python evals/research-workflow/workflow_routing.py evaluate \
  --input evals/research-workflow/fixtures/release_cases.json \
  --output /tmp/research-workflow-routing.json
```

Limits: this suite does not mutate Zotero, perform live scholarly searches,
judge semantic scientific quality, or apply a knowledge-network patch. Those
behaviors remain owned by their skill-specific tests and explicit runtime gates.
