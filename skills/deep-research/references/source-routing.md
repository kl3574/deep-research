# Claim-relative source routing

Trust is relative to a claim. Apply identity, status, version, access, scope, and method gates before assigning authority.

## Academic sources

| Source type | Best use | Required audit | Cannot establish alone |
| --- | --- | --- | --- |
| Mainstream textbook/handbook | Stable concepts, canonical models, derivations, vocabulary | Edition, ISBN/format, chapter, date, errata, bibliography cutoff | Latest findings or exact current values |
| Narrative/authoritative review | Intellectual history, schools, vocabulary, seed papers | Selection method, coverage window, conflicts, accuracy of key citations | Complete recall or pooled effect |
| Scoping/mapping review | Concepts, evidence distribution, gaps | Protocol, search date/scope, screening and extraction | Causal effect or precise magnitude |
| Systematic review | Bounded evidence question | Protocol, last search, databases, inclusion, study-level bias, missing evidence | Claims beyond its included scope |
| Meta-analysis | Comparable effect estimates and uncertainty | Estimand, comparability, heterogeneity, model, intervals, sensitivity | Validity when biased or incompatible studies are pooled |
| Primary study | Exact method, proof, result, new evidence, boundary | Design fit, sample/corpus, controls, uncertainty, registration, data/code | Broad consensus by itself |
| Replication, critique, correction | Robustness and failure discovery | Independence, comparability, response and later updates | Final truth from one success or failure |

For a decisive source:

1. normalize DOI, PMID, ISBN, repository identifier, study ID, and report ID;
2. distinguish preprint, accepted manuscript, Version of Record, updated version, correction, expression of concern, and retraction;
3. use canonical publisher, society, database, or official repository pages;
4. record access as `full_text`, `partial_text`, `abstract_only`, or `metadata_only`;
5. audit reviews by last search date and methods, not title or publication date alone;
6. trace decisive review claims back to primary studies;
7. separate multiple reports of one study to avoid false independence.

Pair identity and access versions explicitly:

```text
canonical_version: Version of Record or authoritative specification identity
read_version: exact PDF/manual/source artifact actually inspected
pairing_basis: DOI, author/title/version statement, repository record, or diff
known_differences: pagination, supplement, accepted-manuscript edits, code ref
```

Do not cite the Version of Record as if it was read when evidence came from an
accepted manuscript or preprint. Cite the canonical identity and disclose the
read copy and any unresolved difference.

Check source status in descending authority:

1. publisher/society record and Crossmark or formal correction/retraction page;
2. domain index such as PubMed when applicable;
3. DOI registry update relations;
4. exact-title correction/retraction search.

An empty lower-level field is only “not found by this route,” not proof that no
correction exists.

Record evidence class separately from source prestige:

`definition | theorem_or_derivation | synthetic_benchmark | real_experiment |
observational_study | review_synthesis | normative_document | implementation |
runtime_observation`

A theorem does not establish empirical prevalence; a synthetic benchmark does
not establish field performance; a review does not make overlapping primary
studies independent; documentation does not prove deployed behavior.

For independence, record shared authors, teams, datasets, code, benchmarks,
funding, and underlying studies. Several papers from one method family or team
are multiple reports, not automatically multiple independent confirmations.

Peer review, DOI presence, citation count, author reputation, journal impact factor, or the phrase “systematic review” is not a quality certificate. Field-specific tools such as AMSTAR 2, ROBIS, RoB 2, or GRADE must be applied only within their scope and with version/domain judgments preserved—not reduced to a universal score.

## Industry and technical sources

| Claim | Best-fit evidence | Limits |
| --- | --- | --- |
| What should happen | Applicable stable standard, versioned official reference/manual | Does not prove implementation conformity |
| What a release supports | Exact-version reference, compatibility/lifecycle policy, release artifact | Documentation may contain defects |
| What the code does | Official upstream full commit SHA, source path, build flags, same-ref tests | Does not prove deployed binary provenance or public support |
| When/why it changed | Release notes, tag/SHA diff, linked merged PR/commit | Changelogs can omit details |
| What target environment does | Authorized minimal reproduction with artifact digest, environment, config, command, output | Observation is local, not universal |
| What may happen later | Official roadmap, maintainer issue/discussion | Provisional; never present as shipped |

Verify official ownership through the vendor site, package metadata, organization identity, or release provenance. Check whether the repository is a fork, mirror, SDK, example, archive, or actual upstream implementation.

Use immutable anchors:

- versioned documentation or archived manual;
- full Git commit SHA permalinks rather than branch links;
- release, tag, commit, and artifact digest as distinct fields;
- image digest rather than mutable container tag;
- API/standard revision, hardware model, firmware, platform, region/tier, and relevant configuration.

SemVer supports compatibility inference only when the project declares and follows it. Standards and specifications require maturity/status, normative vs informative sections, obsoletes/updates relations, and errata checks.

Do not require every evidence mode for every low-risk claim. For a consequential implementation claim, seek at least two complementary modes such as contract plus exact-source/test, or artifact plus target-runtime observation. If one is unavailable, narrow the claim and state the missing link.

## Source registry

```yaml
source_id:
identity:
  title:
  authors_or_owner:
  doi_pmid_isbn_repo:
  canonical_url:
source_type:
publication_or_document_status:
version_or_edition:
git_ref_or_artifact_digest:
publication_or_release_date:
last_updated:
review_last_search_date:
retrieved_at:
access_level:
status_checks:
  correction_retraction_errata_obsolescence:
scope_and_applicability:
exact_locators:
integrity:
  local_path:
  sha256:
role: orientation | support | contradict | qualify | implementation | runtime
limitations:
```

Register the canonical source, not a search result or AI summary. If full text or a paid standard is inaccessible, preserve the gap and avoid pretending to have audited it.
