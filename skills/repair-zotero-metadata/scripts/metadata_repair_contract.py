#!/usr/bin/env python3
"""Build and validate private reviewed repairs for existing Zotero parents."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any


DRAFT_SCHEMA = "ZoteroParentMetadataRepairDraft/v1"
REVIEWED_SCHEMA = "ZoteroReviewedParentMetadataRepair/v1"
SOURCE_EVIDENCE_SIDECAR_SCHEMA = "ZoteroParentMetadataRepairLiveSidecar/v1"
HASH_CONTRACT = "canonical-json-v1"
PROFILE = "journal_article_core_v1"
TRANSITION_POLICY = "fill_or_evidence_bound_replace_v1"
PROFILE_FIELDS = (
    "DOI",
    "creators",
    "publicationTitle",
    "volume",
    "issue",
    "pages",
    "date",
)
FILL_ONLY_FIELDS = {"creators", "publicationTitle", "volume", "issue", "pages"}
EVIDENCE_KINDS = {
    "verified_pdf",
    "publisher_metadata",
    "doi_registry",
    "bibliographic_export",
}
KEY_RE = re.compile(r"^[A-Z0-9]{8}$")
SHA_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
DUPLICATE_TITLE_PREFIX_MIN_CHARS = 20


class ContractError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_value(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        raise ContractError(
            f"{label} keys differ: missing={sorted(expected-actual)} "
            f"unknown={sorted(actual-expected)}"
        )
    return value


def text(
    value: Any,
    label: str,
    *,
    nonempty: bool = True,
    limit: int = 16_384,
) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise ContractError(f"{label} must be a{' non-empty' if nonempty else ''} string")
    if len(value.encode("utf-8")) > limit:
        raise ContractError(f"{label} is too large")
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value):
        raise ContractError(f"{label} contains control characters")
    if value and value != value.strip():
        raise ContractError(f"{label} must be trimmed")
    return value


def positive_int(value: Any, label: str, *, maximum: int | None = None) -> int:
    if type(value) is not int or value <= 0 or (maximum is not None and value > maximum):
        raise ContractError(f"{label} must be a positive integer")
    return value


def nonnegative_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ContractError(f"{label} must be a non-negative integer")
    return value


def item_key(value: Any, label: str) -> str:
    value = text(value, label, limit=8)
    if not KEY_RE.fullmatch(value):
        raise ContractError(f"{label} must be an 8-character Zotero key")
    return value


def sha(value: Any, label: str) -> str:
    value = text(value, label, limit=71)
    if not SHA_RE.fullmatch(value):
        raise ContractError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def normalize_doi(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(
        r"^https?://(?:dx\.)?doi\.org/",
        "",
        value.strip().lower(),
    )


def validate_profile(value: Any, label: str) -> dict[str, Any]:
    profile = exact_keys(value, set(PROFILE_FIELDS), label)
    doi = text(profile["DOI"], f"{label}.DOI", nonempty=False, limit=2048)
    if doi and (doi != normalize_doi(doi) or not DOI_RE.fullmatch(doi)):
        raise ContractError(f"{label}.DOI must be a canonical DOI")
    creators = profile["creators"]
    if not isinstance(creators, list) or len(creators) > 64:
        raise ContractError(f"{label}.creators must be a bounded array")
    creator_fingerprints: list[bytes] = []
    for index, raw_creator in enumerate(creators):
        creator = exact_keys(
            raw_creator,
            {"creatorType", "firstName", "lastName"},
            f"{label}.creators[{index}]",
        )
        if creator["creatorType"] != "author":
            raise ContractError(f"{label}.creators[{index}].creatorType must be author")
        text(creator["firstName"], f"{label}.creators[{index}].firstName")
        text(creator["lastName"], f"{label}.creators[{index}].lastName")
        creator_fingerprints.append(canonical_bytes(creator))
    if len(set(creator_fingerprints)) != len(creator_fingerprints):
        raise ContractError(f"{label}.creators contains duplicates")
    for field in PROFILE_FIELDS:
        if field not in {"DOI", "creators"}:
            text(profile[field], f"{label}.{field}", nonempty=False, limit=4096)
    return profile


def validate_parent(value: Any, label: str) -> dict[str, Any]:
    parent = exact_keys(
        value,
        {
            "key",
            "version",
            "item_type",
            "title",
            "short_title",
            "expected_target_membership",
        },
        label,
    )
    item_key(parent["key"], f"{label}.key")
    positive_int(parent["version"], f"{label}.version")
    if parent["item_type"] != "journalArticle":
        raise ContractError(f"{label}.item_type must be journalArticle")
    text(parent["title"], f"{label}.title")
    text(parent["short_title"], f"{label}.short_title", nonempty=False, limit=4096)
    if parent["expected_target_membership"] is not True:
        raise ContractError(f"{label}.expected_target_membership must be true")
    return parent


def validate_children(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > 100:
        raise ContractError(f"{label} must be a non-empty bounded array")
    keys: list[str] = []
    for index, raw_child in enumerate(value):
        child_label = f"{label}[{index}]"
        if not isinstance(raw_child, dict):
            raise ContractError(f"{child_label} must be an object")
        item_type = raw_child.get("item_type")
        if item_type == "note":
            child = exact_keys(
                raw_child,
                {"key", "version", "item_type", "content_sha256"},
                child_label,
            )
        elif item_type == "attachment":
            child = exact_keys(
                raw_child,
                {
                    "key",
                    "version",
                    "item_type",
                    "content_type",
                    "link_mode",
                    "size_bytes",
                    "content_sha256",
                    "direct_collection_count",
                },
                child_label,
            )
            text(child["content_type"], f"{child_label}.content_type", limit=256)
            if child["link_mode"] not in {
                "imported_file",
                "imported_url",
                "linked_file",
            }:
                raise ContractError(f"{child_label}.link_mode is unsupported")
            positive_int(
                child["size_bytes"],
                f"{child_label}.size_bytes",
                maximum=268_435_456,
            )
            nonnegative_int(
                child["direct_collection_count"],
                f"{child_label}.direct_collection_count",
            )
        else:
            raise ContractError(f"{child_label}.item_type must be note or attachment")
        keys.append(item_key(child["key"], f"{child_label}.key"))
        positive_int(child["version"], f"{child_label}.version")
        sha(child["content_sha256"], f"{child_label}.content_sha256")
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        raise ContractError(f"{label} must be key-sorted and unique")
    return value


def metadata_parent_data(
    parent: dict[str, Any],
    children: list[dict[str, Any]],
    profile: dict[str, Any],
) -> dict[str, Any]:
    return {
        "key": parent["key"],
        "item_type": parent["item_type"],
        "title": parent["title"],
        "short_title": parent["short_title"],
        "target_membership": parent["expected_target_membership"],
        "profile": profile,
        "children": children,
    }


def validate_duplicate_preconditions(
    value: Any,
    label: str,
    *,
    require_digest: bool,
) -> dict[str, Any]:
    expected = {
        "scope",
        "desired_doi_other_parent_keys",
        "title_year_creator_other_parent_keys",
    }
    if require_digest:
        expected.add("sha256")
    duplicate = exact_keys(value, expected, label)
    if duplicate["scope"] != "full_library":
        raise ContractError(f"{label}.scope must be full_library")
    for field in (
        "desired_doi_other_parent_keys",
        "title_year_creator_other_parent_keys",
    ):
        keys = duplicate[field]
        if not isinstance(keys, list) or keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ContractError(f"{label}.{field} must be sorted and unique")
        for index, key in enumerate(keys):
            item_key(key, f"{label}.{field}[{index}]")
        if keys:
            raise ContractError(f"{label} contains duplicate candidates")
    if require_digest:
        sha(duplicate["sha256"], f"{label}.sha256")
        unsigned = {key: item for key, item in duplicate.items() if key != "sha256"}
        if sha256_value(unsigned) != duplicate["sha256"]:
            raise ContractError(f"{label}.sha256 is inconsistent")
    return duplicate


def validate_target(value: Any, label: str) -> dict[str, Any]:
    target = exact_keys(
        value,
        {
            "group_id",
            "library_type",
            "library_type_id",
            "local_library_id",
            "library_name",
            "collection_key",
            "collection_version",
            "collection_path",
            "internal_collection_id",
        },
        label,
    )
    group_id = positive_int(target["group_id"], f"{label}.group_id")
    if target["library_type"] != "group":
        raise ContractError(f"{label}.library_type must be group")
    if positive_int(target["library_type_id"], f"{label}.library_type_id") != group_id:
        raise ContractError(f"{label} group identity is inconsistent")
    positive_int(target["local_library_id"], f"{label}.local_library_id")
    text(target["library_name"], f"{label}.library_name", limit=256)
    item_key(target["collection_key"], f"{label}.collection_key")
    positive_int(target["collection_version"], f"{label}.collection_version")
    path = target["collection_path"]
    if not isinstance(path, list) or not path or len(path) > 32:
        raise ContractError(f"{label}.collection_path is invalid")
    for index, name in enumerate(path):
        text(name, f"{label}.collection_path[{index}]", limit=512)
    if target["internal_collection_id"] is not None:
        positive_int(
            target["internal_collection_id"], f"{label}.internal_collection_id"
        )
    return target


def validate_source_evidence_sidecar_ref(value: Any, label: str) -> dict[str, Any]:
    reference = exact_keys(
        value,
        {"schema", "file_sha256", "content_sha256"},
        label,
    )
    if reference["schema"] != SOURCE_EVIDENCE_SIDECAR_SCHEMA:
        raise ContractError(f"{label}.schema is unsupported")
    sha(reference["file_sha256"], f"{label}.file_sha256")
    sha(reference["content_sha256"], f"{label}.content_sha256")
    return reference


def validate_source_evidence_sidecar(
    value: Path | bytes,
    expected_ref: dict[str, Any],
) -> dict[str, Any]:
    expected_ref = validate_source_evidence_sidecar_ref(
        expected_ref, "source_evidence_sidecar_ref"
    )
    if isinstance(value, Path):
        path = value.expanduser().resolve()
        try:
            if value.is_symlink() or not path.is_file():
                raise OSError("path is not a regular non-symlink file")
            if path.stat().st_mode & 0o777 != 0o600:
                raise OSError("file mode must be 0600")
            payload = path.read_bytes()
        except OSError as exc:
            raise ContractError(f"cannot read source evidence sidecar: {exc}") from exc
    elif isinstance(value, bytes):
        payload = value
    else:
        raise ContractError("source evidence sidecar must be a Path or bytes")
    observed_file_sha256 = "sha256:" + hashlib.sha256(payload).hexdigest()
    if observed_file_sha256 != expected_ref["file_sha256"]:
        raise ContractError("source evidence sidecar file_sha256 mismatch")
    try:
        sidecar = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"source evidence sidecar is invalid JSON: {exc}") from exc
    if not isinstance(sidecar, dict):
        raise ContractError("source evidence sidecar must be an object")
    if sidecar.get("schema") != expected_ref["schema"]:
        raise ContractError("source evidence sidecar schema mismatch")
    observed_content_sha256 = sidecar.get("content_sha256")
    sha(observed_content_sha256, "source evidence sidecar.content_sha256")
    unsigned = {
        key: item for key, item in sidecar.items() if key != "content_sha256"
    }
    if sha256_value(unsigned) != observed_content_sha256:
        raise ContractError("source evidence sidecar content_sha256 is inconsistent")
    if observed_content_sha256 != expected_ref["content_sha256"]:
        raise ContractError("source evidence sidecar content_sha256 mismatch")
    return copy.deepcopy(expected_ref)


def validate_transition(
    expected: dict[str, Any], desired: dict[str, Any]
) -> list[str]:
    changed = sorted(field for field in PROFILE_FIELDS if expected[field] != desired[field])
    if not changed:
        raise ContractError("repair profiles are unchanged")
    for field in changed:
        if field == "creators":
            if expected[field] or not desired[field]:
                raise ContractError("creators may only be filled from an empty list in v1")
        else:
            if not desired[field]:
                raise ContractError(f"{field} cannot be cleared")
            if field in FILL_ONLY_FIELDS and expected[field]:
                raise ContractError(f"{field} may only be filled from an empty value in v1")
    return changed


def _validate_source(
    value: Any,
    changed_fields: list[str],
    expected_profile: dict[str, Any],
    desired_profile: dict[str, Any],
    evidence_pdf_sha256: str,
) -> dict[str, Any]:
    source = exact_keys(
        value,
        {"hash_contract", "evidence_artifacts", "field_evidence"},
        "source",
    )
    if source["hash_contract"] != HASH_CONTRACT:
        raise ContractError("source.hash_contract must be canonical-json-v1")
    artifacts = source["evidence_artifacts"]
    if not isinstance(artifacts, list) or not artifacts or len(artifacts) > 100:
        raise ContractError("source.evidence_artifacts must be a non-empty bounded array")
    artifact_kinds: dict[str, str] = {}
    artifact_hashes: dict[str, str] = {}
    artifact_ids: list[str] = []
    for index, raw_artifact in enumerate(artifacts):
        label = f"source.evidence_artifacts[{index}]"
        artifact = exact_keys(
            raw_artifact,
            {"id", "kind", "locator", "retrieved_at", "sha256"},
            label,
        )
        artifact_id = text(artifact["id"], f"{label}.id", limit=64)
        if not ID_RE.fullmatch(artifact_id):
            raise ContractError(f"{label}.id is invalid")
        if artifact["kind"] not in EVIDENCE_KINDS:
            raise ContractError(f"{label}.kind is unsupported")
        text(artifact["locator"], f"{label}.locator", limit=16_384)
        text(artifact["retrieved_at"], f"{label}.retrieved_at", limit=64)
        sha(artifact["sha256"], f"{label}.sha256")
        artifact_ids.append(artifact_id)
        artifact_kinds[artifact_id] = artifact["kind"]
        artifact_hashes[artifact_id] = artifact["sha256"]
    if artifact_ids != sorted(artifact_ids) or len(artifact_ids) != len(set(artifact_ids)):
        raise ContractError("source.evidence_artifacts must be id-sorted and unique")
    field_evidence = source["field_evidence"]
    if not isinstance(field_evidence, dict) or set(field_evidence) != set(changed_fields):
        raise ContractError("source.field_evidence must contain exactly the changed fields")
    for field in changed_fields:
        ids = field_evidence[field]
        if not isinstance(ids, list) or not ids or ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ContractError(f"source.field_evidence.{field} must be non-empty, sorted, and unique")
        if any(identifier not in artifact_kinds for identifier in ids):
            raise ContractError(f"source.field_evidence.{field} references unknown evidence")
        for identifier in ids:
            if (
                artifact_kinds[identifier] == "verified_pdf"
                and artifact_hashes[identifier] != evidence_pdf_sha256
            ):
                raise ContractError(
                    "verified PDF evidence sha256 must match the bound PDF child"
                )
        if field == "DOI" and expected_profile[field] and expected_profile[field] != desired_profile[field]:
            kinds = {artifact_kinds[identifier] for identifier in ids}
            if len(ids) < 2:
                raise ContractError("DOI replacement requires two evidence artifacts")
            if "verified_pdf" not in kinds or not kinds.intersection(
                {"publisher_metadata", "doi_registry"}
            ):
                raise ContractError(
                    "DOI replacement requires verified PDF and publisher or DOI-registry evidence"
                )
        if (
            field == "date"
            and expected_profile[field]
            and expected_profile[field] != desired_profile[field]
        ):
            kinds = {artifact_kinds[identifier] for identifier in ids}
            if len(ids) < 2:
                raise ContractError("date replacement requires two evidence artifacts")
            if "verified_pdf" not in kinds:
                raise ContractError("date replacement requires verified PDF evidence")
    return source


def build_reviewed_source(
    draft: Any,
    *,
    source_evidence_sidecar: Path | bytes,
) -> dict[str, Any]:
    draft = exact_keys(
        draft,
        {
            "schema",
            "status",
            "created_at",
            "private",
            "source_evidence_sidecar_ref",
            "source",
            "target",
            "entry",
            "summary",
        },
        "draft",
    )
    if draft["schema"] != DRAFT_SCHEMA or draft["status"] != "reviewed":
        raise ContractError("draft schema or status mismatch")
    text(draft["created_at"], "draft.created_at", limit=64)
    if draft["private"] is not True:
        raise ContractError("draft.private must be true")
    source_evidence_sidecar_ref = validate_source_evidence_sidecar(
        source_evidence_sidecar,
        copy.deepcopy(draft["source_evidence_sidecar_ref"]),
    )
    target = validate_target(copy.deepcopy(draft["target"]), "draft.target")
    entry = exact_keys(
        draft["entry"],
        {"parent", "children", "evidence_pdf_key", "duplicate_preconditions", "repair"},
        "draft.entry",
    )
    parent = validate_parent(copy.deepcopy(entry["parent"]), "draft.entry.parent")
    children = validate_children(copy.deepcopy(entry["children"]), "draft.entry.children")
    evidence_pdf_key = item_key(entry["evidence_pdf_key"], "draft.entry.evidence_pdf_key")
    evidence_pdf_children = [
        child
        for child in children
        if child["key"] == evidence_pdf_key
        and child["item_type"] == "attachment"
        and child["content_type"] == "application/pdf"
    ]
    if len(evidence_pdf_children) != 1:
        raise ContractError("evidence_pdf_key must identify one bound PDF child")
    evidence_pdf_sha256 = evidence_pdf_children[0]["content_sha256"]
    duplicate = validate_duplicate_preconditions(
        copy.deepcopy(entry["duplicate_preconditions"]),
        "draft.entry.duplicate_preconditions",
        require_digest=False,
    )
    repair = exact_keys(
        entry["repair"],
        {"profile", "transition_policy", "expected_profile", "desired_profile"},
        "draft.entry.repair",
    )
    if repair["profile"] != PROFILE or repair["transition_policy"] != TRANSITION_POLICY:
        raise ContractError("repair profile or transition policy mismatch")
    expected_profile = validate_profile(
        copy.deepcopy(repair["expected_profile"]),
        "draft.entry.repair.expected_profile",
    )
    desired_profile = validate_profile(
        copy.deepcopy(repair["desired_profile"]),
        "draft.entry.repair.desired_profile",
    )
    changed_fields = validate_transition(expected_profile, desired_profile)
    source = _validate_source(
        copy.deepcopy(draft["source"]),
        changed_fields,
        expected_profile,
        desired_profile,
        evidence_pdf_sha256,
    )
    if not isinstance(draft["summary"], dict):
        raise ContractError("draft.summary must be an object")
    duplicate_with_hash = {**duplicate, "sha256": sha256_value(duplicate)}
    reviewed_repair = {
        "profile": PROFILE,
        "transition_policy": TRANSITION_POLICY,
        "expected_profile": expected_profile,
        "expected_profile_sha256": sha256_value(expected_profile),
        "desired_profile": desired_profile,
        "desired_profile_sha256": sha256_value(desired_profile),
        "changed_fields": changed_fields,
        "expected_parent_data_sha256": sha256_value(
            metadata_parent_data(parent, children, expected_profile)
        ),
        "desired_parent_data_sha256": sha256_value(
            metadata_parent_data(parent, children, desired_profile)
        ),
    }
    reviewed_entry = {
        "parent": parent,
        "children": children,
        "children_sha256": sha256_value(children),
        "evidence_pdf_key": evidence_pdf_key,
        "duplicate_preconditions": duplicate_with_hash,
        "repair": reviewed_repair,
    }
    reviewed_entry["entry_sha256"] = sha256_value(reviewed_entry)
    reviewed = {
        "schema": REVIEWED_SCHEMA,
        "status": "reviewed_requires_bridge_compile",
        "created_at": draft["created_at"],
        "private": True,
        "source_evidence_sidecar_ref": source_evidence_sidecar_ref,
        "source": source,
        "target": target,
        "entry": reviewed_entry,
        "summary": copy.deepcopy(draft["summary"]),
        "executable": False,
        "execution_contract": "compile-preview-apply-readback",
    }
    reviewed["manifest_sha256"] = sha256_value(reviewed)
    return validate_reviewed_source(reviewed)


def validate_reviewed_source(value: Any) -> dict[str, Any]:
    source = exact_keys(
        value,
        {
            "schema",
            "status",
            "created_at",
            "private",
            "source_evidence_sidecar_ref",
            "source",
            "target",
            "entry",
            "summary",
            "executable",
            "execution_contract",
            "manifest_sha256",
        },
        "reviewed source",
    )
    if source["schema"] != REVIEWED_SCHEMA or source["status"] != "reviewed_requires_bridge_compile":
        raise ContractError("reviewed source schema or status mismatch")
    text(source["created_at"], "reviewed source.created_at", limit=64)
    if source["private"] is not True or source["executable"] is not False:
        raise ContractError("reviewed source privacy/executable boundary mismatch")
    validate_source_evidence_sidecar_ref(
        source["source_evidence_sidecar_ref"],
        "reviewed source.source_evidence_sidecar_ref",
    )
    if source["execution_contract"] != "compile-preview-apply-readback":
        raise ContractError("reviewed source execution_contract mismatch")
    validate_target(source["target"], "reviewed source.target")
    entry = exact_keys(
        source["entry"],
        {
            "parent",
            "children",
            "children_sha256",
            "evidence_pdf_key",
            "duplicate_preconditions",
            "repair",
            "entry_sha256",
        },
        "reviewed source.entry",
    )
    parent = validate_parent(entry["parent"], "reviewed source.entry.parent")
    children = validate_children(entry["children"], "reviewed source.entry.children")
    if sha256_value(children) != entry["children_sha256"]:
        raise ContractError("reviewed source.entry.children_sha256 is inconsistent")
    item_key(entry["evidence_pdf_key"], "reviewed source.entry.evidence_pdf_key")
    evidence_pdf_children = [
        child
        for child in children
        if child["key"] == entry["evidence_pdf_key"]
        and child["item_type"] == "attachment"
        and child["content_type"] == "application/pdf"
    ]
    if len(evidence_pdf_children) != 1:
        raise ContractError("reviewed source evidence PDF binding is invalid")
    evidence_pdf_sha256 = evidence_pdf_children[0]["content_sha256"]
    validate_duplicate_preconditions(
        entry["duplicate_preconditions"],
        "reviewed source.entry.duplicate_preconditions",
        require_digest=True,
    )
    repair = exact_keys(
        entry["repair"],
        {
            "profile",
            "transition_policy",
            "expected_profile",
            "expected_profile_sha256",
            "desired_profile",
            "desired_profile_sha256",
            "changed_fields",
            "expected_parent_data_sha256",
            "desired_parent_data_sha256",
        },
        "reviewed source.entry.repair",
    )
    if repair["profile"] != PROFILE or repair["transition_policy"] != TRANSITION_POLICY:
        raise ContractError("reviewed source repair profile or transition policy mismatch")
    expected_profile = validate_profile(
        repair["expected_profile"], "reviewed source.entry.repair.expected_profile"
    )
    desired_profile = validate_profile(
        repair["desired_profile"], "reviewed source.entry.repair.desired_profile"
    )
    if sha256_value(expected_profile) != repair["expected_profile_sha256"]:
        raise ContractError("reviewed source repair expected_profile_sha256 is inconsistent")
    if sha256_value(desired_profile) != repair["desired_profile_sha256"]:
        raise ContractError("reviewed source repair desired_profile_sha256 is inconsistent")
    changed_fields = validate_transition(expected_profile, desired_profile)
    if repair["changed_fields"] != changed_fields:
        raise ContractError("reviewed source repair changed_fields is inconsistent")
    _validate_source(
        source["source"],
        changed_fields,
        expected_profile,
        desired_profile,
        evidence_pdf_sha256,
    )
    if sha256_value(metadata_parent_data(parent, children, expected_profile)) != repair[
        "expected_parent_data_sha256"
    ]:
        raise ContractError("reviewed source repair expected_parent_data_sha256 is inconsistent")
    if sha256_value(metadata_parent_data(parent, children, desired_profile)) != repair[
        "desired_parent_data_sha256"
    ]:
        raise ContractError("reviewed source repair desired_parent_data_sha256 is inconsistent")
    unsigned_entry = {key: item for key, item in entry.items() if key != "entry_sha256"}
    if sha256_value(unsigned_entry) != entry["entry_sha256"]:
        raise ContractError("reviewed source.entry.entry_sha256 is inconsistent")
    if not isinstance(source["summary"], dict):
        raise ContractError("reviewed source.summary must be an object")
    unsigned_source = {
        key: item for key, item in source.items() if key != "manifest_sha256"
    }
    if sha256_value(unsigned_source) != source["manifest_sha256"]:
        raise ContractError("reviewed source.manifest_sha256 is inconsistent")
    return source


def profile_from_zotero_data(data: dict[str, Any]) -> dict[str, Any]:
    creators: list[dict[str, str]] = []
    for raw_creator in data.get("creators", []):
        if not isinstance(raw_creator, dict):
            raise ContractError("live creators are malformed")
        creators.append(
            {
                "creatorType": str(raw_creator.get("creatorType", "")),
                "firstName": str(raw_creator.get("firstName", "")),
                "lastName": str(raw_creator.get("lastName", "")),
            }
        )
    profile = {
        "DOI": normalize_doi(data.get("DOI", "")),
        "creators": creators,
        "publicationTitle": str(data.get("publicationTitle", "") or ""),
        "volume": str(data.get("volume", "") or ""),
        "issue": str(data.get("issue", "") or ""),
        "pages": str(data.get("pages", "") or ""),
        "date": str(data.get("date", "") or ""),
    }
    return validate_profile(profile, "live profile")


def _duplicate_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "")).lower()
    return "".join(
        character
        for character in normalized
        if unicodedata.category(character)[0] in {"L", "N"}
    )


def _year(value: Any) -> str:
    match = re.search(r"(?:^|\D)(\d{4})(?:\D|$)", str(value or ""))
    return match.group(1) if match else ""


def find_duplicate_candidates(
    records: list[dict[str, Any]],
    *,
    current_key: str,
    title: str,
    desired_profile: dict[str, Any],
) -> dict[str, list[str]]:
    desired_doi = normalize_doi(desired_profile["DOI"])
    desired_title = _duplicate_text(title)
    desired_year = _year(desired_profile["date"])
    desired_creators = {
        _duplicate_text(creator["lastName"])
        for creator in desired_profile["creators"]
        if _duplicate_text(creator["lastName"])
    }
    doi_matches: list[str] = []
    title_matches: list[str] = []
    for record in records:
        data = record.get("data") if isinstance(record, dict) else None
        if not isinstance(data, dict):
            raise ContractError("full-library duplicate scan record is malformed")
        key = item_key(data.get("key"), "duplicate scan parent.key")
        if key == current_key or data.get("itemType") in {"note", "attachment"}:
            continue
        observed_doi = normalize_doi(data.get("DOI", ""))
        if desired_doi and observed_doi == desired_doi:
            doi_matches.append(key)
        observed_title = _duplicate_text(data.get("title", ""))
        observed_year = _year(data.get("date", ""))
        observed_creators = {
            _duplicate_text(creator.get("lastName", creator.get("name", "")))
            for creator in data.get("creators", [])
            if isinstance(creator, dict)
            and _duplicate_text(creator.get("lastName", creator.get("name", "")))
        }
        title_exact = bool(desired_title) and desired_title == observed_title
        title_prefix_related = (
            bool(desired_title)
            and bool(observed_title)
            and not title_exact
            and min(len(desired_title), len(observed_title))
            >= DUPLICATE_TITLE_PREFIX_MIN_CHARS
            and (
                desired_title.startswith(observed_title)
                or observed_title.startswith(desired_title)
            )
        )
        creator_overlap = bool(desired_creators and observed_creators) and not (
            desired_creators.isdisjoint(observed_creators)
        )
        title_creator_related = (
            title_exact
            and (not desired_creators or not observed_creators or creator_overlap)
        ) or (title_prefix_related and creator_overlap)
        if (
            title_creator_related
            and desired_year
            and observed_year == desired_year
        ):
            title_matches.append(key)
    return {
        "desired_doi_other_parent_keys": sorted(set(doi_matches)),
        "title_year_creator_other_parent_keys": sorted(set(title_matches)),
    }


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read JSON {path}: {exc}") from exc


def write_private_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as exc:
        raise ContractError(f"refusing to overwrite {path}: {exc}") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-reviewed-source")
    build.add_argument("draft", type=Path)
    build.add_argument("output", type=Path)
    build.add_argument("--source-evidence-sidecar", required=True, type=Path)
    validate = sub.add_parser("validate-reviewed-source")
    validate.add_argument("source", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-reviewed-source":
            reviewed = build_reviewed_source(
                read_json(args.draft),
                source_evidence_sidecar=args.source_evidence_sidecar,
            )
            write_private_json(args.output, reviewed)
            print(
                json.dumps(
                    {
                        "status": "built",
                        "output": str(args.output.expanduser().resolve()),
                        "manifest_sha256": reviewed["manifest_sha256"],
                    },
                    sort_keys=True,
                )
            )
            return 0
        reviewed = validate_reviewed_source(read_json(args.source))
        print(
            json.dumps(
                {"status": "valid", "manifest_sha256": reviewed["manifest_sha256"]},
                sort_keys=True,
            )
        )
        return 0
    except ContractError as exc:
        print(f"metadata repair contract error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
