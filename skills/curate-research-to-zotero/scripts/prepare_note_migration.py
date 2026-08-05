#!/usr/bin/env python3
"""Stage non-destructive schema-9 migrations and approved child-note creation.

The script reads Zotero's local API, writes original and migrated HTML files to
an external staging directory, and records hashes and validation results. It
never writes to Zotero.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import stat
from collections.abc import Callable
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

from verify_note_html import validate_note
from paper_knowledge_note import (
    ContractError as ProjectionContractError,
    validate_projection_manifest,
)


BASE_URL = "http://127.0.0.1:23119"
ITEM_KEY_PATTERN = re.compile(r"^[A-Z0-9]{8}$")
SUPPORTED_PDF_LINK_MODES = {
    "imported_file",
    "imported_url",
    "linked_file",
}
PARENT_DATA_SNAPSHOT_SCHEMA = "zotero-item-bibliographic-v1"
PARENT_DATA_SNAPSHOT_EXCLUDED_FIELDS = frozenset(
    {
        "accessDate",
        "citationKey",
        "collections",
        "createdByUserID",
        "dateAdded",
        "dateModified",
        "deleted",
        "inPublications",
        "key",
        "lastModifiedByUserID",
        "libraryCatalog",
        "relations",
        "synced",
        "tags",
        "version",
    }
)
HTML_VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
HTML_BLOCK_ELEMENTS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "div",
    "dl",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "ul",
}


class AmbiguousPDFAttachments(RuntimeError):
    def __init__(self, keys: list[str]) -> None:
        self.keys = keys
        super().__init__(
            "multiple PDF attachments require an explicit parent-to-attachment map"
        )


def get_json(
    path: str,
    *,
    method: str = "GET",
    payload: object | None = None,
) -> object:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        BASE_URL + path,
        data=data,
        method=method.upper(),
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def get_all_json(path: str, *, page_size: int = 100) -> list[dict[str, object]]:
    if type(page_size) is not int or page_size <= 0:
        raise ValueError("page_size must be a positive integer")
    collected: list[dict[str, object]] = []
    observed_full_pages: set[tuple[str, ...]] = set()
    start = 0
    while True:
        separator = "&" if "?" in path else "?"
        page = get_json(f"{path}{separator}limit={page_size}&start={start}")
        if not isinstance(page, list):
            raise RuntimeError(f"paginated response at start={start} was not an array")
        if any(not isinstance(item, dict) for item in page):
            raise RuntimeError(
                f"paginated response at start={start} contains a non-object item"
            )
        if len(page) > page_size:
            raise RuntimeError(
                f"paginated response at start={start} exceeds requested limit"
            )
        collected.extend(page)
        if len(page) < page_size:
            return collected
        page_keys = tuple(str(item.get("key") or "") for item in page)
        if page_keys in observed_full_pages:
            raise RuntimeError("pagination did not advance; refusing a partial inventory")
        observed_full_pages.add(page_keys)
        start += page_size


def get_text(path: str) -> str:
    with urllib.request.urlopen(BASE_URL + path, timeout=20) as response:
        return response.read().decode("utf-8")


def normalize_collection_identifier(value: object) -> str:
    if type(value) is bool or value is None:
        return ""
    if type(value) is int:
        return str(value)
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    normalized = text.upper()
    if normalized.startswith("C") and normalized[1:].isdigit():
        return normalized[1:]
    return text


def parse_positive_int(value: object, field: str) -> int:
    if isinstance(value, str):
        stripped = value.strip().upper()
        if stripped[:1] in {"C", "L"}:
            value = stripped[1:]
    text = normalize_collection_identifier(value)
    if type(value) is bool or not text or not text.isdigit():
        raise ValueError(f"{field} is invalid")
    parsed = int(text)
    if parsed <= 0:
        raise ValueError(f"{field} must be positive")
    return parsed


def parse_collection_version(raw_version: object) -> int:
    if type(raw_version) is bool:
        raise ValueError("collection version has invalid bool type")
    if type(raw_version) is int:
        return raw_version
    if isinstance(raw_version, str) and raw_version.isdigit():
        return int(raw_version)
    raise ValueError(f"collection version is invalid: {raw_version!r}")


def resolve_selected_path(targets: object, selected_id: str, library_id: int) -> list[str]:
    if not isinstance(targets, list):
        raise RuntimeError("selected target tree is missing")
    selected_numeric_id = normalize_collection_identifier(selected_id)
    if not selected_numeric_id.isdigit():
        raise RuntimeError("selected collection id is invalid")
    selected_tree_id = f"C{selected_numeric_id}"
    stack: list[dict[str, str]] = []
    found: list[str] | None = None
    for index, target in enumerate(targets):
        if not isinstance(target, dict):
            raise RuntimeError(f"selected target tree node {index} is not an object")
        level = target.get("level")
        if type(level) is not int or level < 0:
            raise RuntimeError("selected target tree node level is invalid")
        if level > len(stack):
            raise RuntimeError("selected target tree path is malformed")
        stack = stack[:level]
        raw_node_id = target.get("id")
        if type(raw_node_id) is bool:
            raise RuntimeError("selected target tree node id is invalid")
        if type(raw_node_id) is int:
            node_id = f"{'L' if level == 0 else 'C'}{raw_node_id}"
        elif isinstance(raw_node_id, str):
            node_id = raw_node_id.strip().upper()
        else:
            node_id = ""
        expected_prefix = "L" if level == 0 else "C"
        if (
            not node_id.startswith(expected_prefix)
            or not node_id[1:].isdigit()
        ):
            raise RuntimeError("selected target tree node id is invalid")
        node_name = str(target.get("name") or "").strip()
        if not node_id:
            raise RuntimeError("selected target tree node id is invalid")
        if not node_name:
            raise RuntimeError("selected target tree node name is missing")
        if any(item["id"] == node_id for item in stack):
            raise RuntimeError("selected target path contains a cycle")
        stack.append({"id": node_id, "name": node_name})
        if node_id == selected_tree_id:
            if level == 0:
                raise RuntimeError("selected target is a library, not a collection")
            root_id = stack[0]["id"]
            if root_id != f"L{library_id}":
                raise RuntimeError("selected target root does not match selected library")
            path = [item["name"] for item in stack[1:]]
            if not path:
                raise RuntimeError("selected target path is empty")
            if found is not None and found != path:
                raise RuntimeError("selected target path is ambiguous")
            found = path
    if found is None:
        raise RuntimeError("selected target path is missing")
    return found


def selected_target() -> dict[str, object]:
    payload = get_json(
        "/connector/getSelectedCollection",
        method="POST",
        payload={},
    )
    if not isinstance(payload, dict):
        raise RuntimeError("selected target is malformed")
    library_id = parse_positive_int(payload.get("libraryID"), "libraryID")
    library_name = str(payload.get("libraryName") or "").strip()
    if not library_name:
        raise RuntimeError("selected target libraryName is missing")
    selected_id = normalize_collection_identifier(payload.get("id"))
    if not selected_id:
        raise RuntimeError("selected collection id is missing")
    collection_name = str(payload.get("name") or "").strip()
    if not collection_name:
        raise RuntimeError("selected collection name is missing")
    if payload.get("editable") is not True or payload.get("filesEditable") is not True:
        raise RuntimeError("selected collection is not writable")
    selected_path = resolve_selected_path(
        payload.get("targets"),
        selected_id=selected_id,
        library_id=library_id,
    )
    return {
        "library_id": library_id,
        "library_name": library_name,
        "local_collection_id": parse_positive_int(selected_id, "collection id"),
        "collection_path": selected_path,
        "collection_name": collection_name,
        "collection_key": str(payload.get("key") or ""),
    }


def resolve_collection_path(
    group_id: int,
    collection_key: str,
    *,
    get_collection: Callable[[str], object] = lambda path: get_json(path),
) -> dict[str, object]:
    if not isinstance(collection_key, str) or not collection_key.strip():
        raise RuntimeError("collection key is empty")
    current = collection_key.strip()
    if not re.fullmatch(r"[A-Za-z0-9]+", current):
        raise RuntimeError("collection key is invalid")
    seen: set[str] = set()
    names: list[str] = []
    collection_version: int | None = None
    library_name: str | None = None
    while current:
        if current in seen:
            raise RuntimeError("collection path contains a cycle")
        seen.add(current)
        collection = get_collection(f"/api/groups/{group_id}/collections/{urllib.parse.quote(current)}")
        if not isinstance(collection, dict):
            raise RuntimeError("collection response is malformed")
        data = collection.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("collection data is malformed")
        library = collection.get("library")
        if not isinstance(library, dict):
            raise RuntimeError("collection library identity is missing")
        observed_group_id = parse_positive_int(
            library.get("id"),
            "collection library group id",
        )
        observed_library_name = str(library.get("name") or "").strip()
        if (
            library.get("type") != "group"
            or observed_group_id != group_id
            or not observed_library_name
        ):
            raise RuntimeError("collection library identity does not match group")
        if library_name is None:
            library_name = observed_library_name
        elif library_name != observed_library_name:
            raise RuntimeError("collection hierarchy crosses library identities")
        name = str(data.get("name") or "").strip()
        if not name:
            raise RuntimeError("collection name is missing")
        names.append(name)
        if collection_version is None:
            collection_version = parse_collection_version(collection.get("version"))
        parent = data.get("parentCollection")
        if parent is False or parent is None:
            break
        if type(parent) is bool:
            raise RuntimeError("parent collection id is invalid")
        if not isinstance(parent, str) or not re.fullmatch(
            r"[A-Za-z0-9]+",
            parent,
        ):
            raise RuntimeError("parent collection id is invalid")
        current = parent
    if not names:
        raise RuntimeError("failed to resolve collection path")
    if collection_version is None:
        raise RuntimeError("collection version is missing")
    if library_name is None:
        raise RuntimeError("collection library name is missing")
    return {
        "collection_path": list(reversed(names)),
        "collection_version": collection_version,
        "library_name": library_name,
        "group_id": group_id,
    }


def resolve_target_contract(
    group_id: int,
    collection_key: str,
    *,
    expected_collection_name: str | None = None,
) -> dict[str, object]:
    group_id = parse_positive_int(group_id, "group_id")
    selected = selected_target()
    resolved_collection = resolve_collection_path(group_id, collection_key)
    collection_path = resolved_collection["collection_path"]
    collection_version = resolved_collection["collection_version"]
    if selected["library_name"] != resolved_collection["library_name"]:
        raise RuntimeError(
            "selected library name does not match the approved group library"
        )
    if not collection_path:
        raise RuntimeError("collection path is empty")
    if collection_path[-1] != selected["collection_name"]:
        raise RuntimeError(
            f"collection name mismatch: {collection_path[-1]!r} != {selected['collection_name']!r}"
        )
    if expected_collection_name and collection_path[-1] != expected_collection_name:
        raise RuntimeError(
            f"collection name mismatch: {collection_path[-1]!r} != {expected_collection_name!r}"
        )
    if collection_path != selected["collection_path"]:
        raise RuntimeError(
            "selected collection path does not match the approved collection path"
        )
    return {
        "group_id": group_id,
        "library_id": selected["library_id"],
        "library_name": selected["library_name"],
        "local_collection_id": selected["local_collection_id"],
        "collection_key": collection_key,
        "collection_name": collection_path[-1],
        "collection_path": collection_path,
        "collection_version": collection_version,
    }


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_projection_manifests(
    paths: list[Path] | None,
) -> dict[str, dict[str, object]]:
    manifests: dict[str, dict[str, object]] = {}
    for raw_path in paths or []:
        candidate = raw_path.expanduser()
        if not candidate.is_absolute():
            raise ValueError("projection manifest paths must be absolute")
        try:
            candidate = candidate.resolve(strict=True)
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            validated = validate_projection_manifest(
                payload,
                require_upstream_provenance=True,
                verify_upstream_provenance=True,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ProjectionContractError) as exc:
            raise ValueError(f"invalid projection manifest {candidate}: {exc}") from exc
        html_sha256 = str(validated["html_sha256"])
        if html_sha256 in manifests:
            raise ValueError(
                "projection manifests contain duplicate HTML bindings: "
                f"{html_sha256}"
            )
        manifests[html_sha256] = {
            "manifest": validated,
            "path": str(candidate),
        }
    return manifests


def projection_binding_for_html(
    rendered: str,
    source_path: Path,
    manifests_by_html_sha256: dict[str, dict[str, object]],
    used_html_sha256: set[str],
) -> dict[str, object]:
    html_sha256 = sha256_bytes(rendered.encode("utf-8"))
    _errors, _warnings, summary = validate_note(rendered)
    is_projection = summary.get("note_contract") == "PaperKnowledgeNote/v2"
    available = manifests_by_html_sha256.get(html_sha256)
    if not is_projection:
        if available is not None:
            raise ValueError(
                "projection manifest HTML is not a PaperKnowledgeNote/v2 document"
            )
        return {}
    if available is None:
        raise ValueError(
            "PaperKnowledgeNote/v2 HTML requires a matching --projection-manifest"
        )
    try:
        validated = validate_projection_manifest(
            available["manifest"],
            rendered=rendered,
            require_upstream_provenance=True,
            verify_upstream_provenance=True,
        )
    except ProjectionContractError as exc:
        raise ValueError(f"projection manifest gate failed: {exc}") from exc
    used_html_sha256.add(html_sha256)
    return {
        "projection_manifest": validated,
        "projection_manifest_path": str(available["path"]),
        "projection_source_path": str(source_path),
        "projection_source_sha256": html_sha256,
    }


def parent_data_snapshot_sha256(parent_data: dict[str, object]) -> str:
    """Hash stable bibliographic fields while excluding operational metadata."""
    snapshot = {
        key: value
        for key, value in parent_data.items()
        if key not in PARENT_DATA_SNAPSHOT_EXCLUDED_FIELDS
    }
    bound_snapshot = {
        "data": snapshot,
        "schema": PARENT_DATA_SNAPSHOT_SCHEMA,
    }
    try:
        canonical = json.dumps(
            bound_snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "parent item data is not canonical JSON"
        ) from exc
    return sha256_bytes(canonical.encode("utf-8"))


def ensure_staging_destination(output_dir: Path) -> None:
    if output_dir.is_symlink():
        raise RuntimeError("staging destination must not be a symbolic link")
    try:
        output_stat = output_dir.stat()
    except OSError as exc:
        raise RuntimeError(f"staging destination is unavailable: {exc}") from exc
    if not stat.S_ISDIR(output_stat.st_mode):
        raise RuntimeError("staging destination must be a directory")
    if output_stat.st_uid != os.getuid():
        raise RuntimeError("staging destination must be owned by the current user")
    if stat.S_IMODE(output_stat.st_mode) & 0o022:
        raise RuntimeError(
            "staging destination must not be writable by group or other users"
        )
    manifest_path = output_dir / "migration_manifest.json"
    if manifest_path.exists() or manifest_path.is_symlink():
        raise RuntimeError(
            "staging destination already contains migration_manifest.json; "
            "use a new output directory"
        )
    for name in ("originals", "updated"):
        directory = output_dir / name
        if directory.exists() or directory.is_symlink():
            raise RuntimeError(
                f"staging destination {directory} is already reserved; "
                "use a new output directory"
            )


def write_bytes_exclusive(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
    except FileExistsError as exc:
        raise RuntimeError(f"refusing to overwrite staging artifact: {path}") from exc


def write_text_exclusive(path: Path, text: str) -> None:
    write_bytes_exclusive(path, text.encode("utf-8"))


def strip_tags(fragment: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", fragment, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(html.unescape(text).split())


_ZOTERO_NOTE_CONTROL_CHARACTERS = re.compile(
    r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]"
)
_HTML_ASCII_WHITESPACE = " \t\r\n\f"
_HTML_ASCII_WHITESPACE_RUN = re.compile(r"[ \t\r\n\f]+")
_INLINE_WHITE_SPACE_DECLARATION = re.compile(
    r"(?:^|;)[ \t\r\n\f]*white-space[ \t\r\n\f]*:",
    flags=re.I,
)


def trim_note_html_for_comparison(html_text: str) -> str:
    """Normalize note HTML using the Zotero trim behavior used before persistence."""
    without_control = _ZOTERO_NOTE_CONTROL_CHARACTERS.sub("", html_text)
    return without_control.strip()


def _is_html_ascii_whitespace(value: str) -> bool:
    return not value or not re.search(r"[^ \t\r\n\f]", value)


class _ComparisonElement:
    def __init__(
        self,
        tag: str,
        attributes: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.tag = tag
        self.attributes = attributes
        self.children: list[_ComparisonElement | str] = []


class _ComparisonHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.document = _ComparisonElement("#document")
        self.stack = [self.document]
        self.valid = True

    def _append_element(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        *,
        self_closing: bool,
    ) -> None:
        clean_attributes = tuple(
            sorted((key, value or "") for key, value in attrs)
        )
        element = _ComparisonElement(tag, clean_attributes)
        self.stack[-1].children.append(element)
        if not self_closing and tag not in HTML_VOID_ELEMENTS:
            self.stack.append(element)

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._append_element(tag, attrs, self_closing=False)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._append_element(tag, attrs, self_closing=True)

    def handle_endtag(self, tag: str) -> None:
        if tag in HTML_VOID_ELEMENTS:
            return
        if len(self.stack) == 1 or self.stack[-1].tag != tag:
            self.valid = False
            return
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].children.append(data)

    def close(self) -> None:
        super().close()
        if len(self.stack) != 1:
            self.valid = False


def _semantic_neighbor(
    children: list[_ComparisonElement | str],
    index: int,
    direction: int,
) -> _ComparisonElement | str | None:
    index += direction
    while 0 <= index < len(children):
        candidate = children[index]
        if (
            not isinstance(candidate, str)
            or not _is_html_ascii_whitespace(candidate)
        ):
            return candidate
        index += direction
    return None


def _is_block_comparison_node(node: _ComparisonElement | str | None) -> bool:
    return isinstance(node, _ComparisonElement) and node.tag in HTML_BLOCK_ELEMENTS


def _is_table_row_element(node: tuple[object, ...]) -> bool:
    return len(node) == 4 and node[0] == "element" and node[1] == "tr"


def _is_attribute_free_table_section(node: tuple[object, ...]) -> bool:
    return (
        len(node) == 4
        and node[0] == "element"
        and node[1] in {"thead", "tbody", "tfoot"}
        and node[2] == ()
        and all(_is_table_row_element(child) for child in node[3])
    )


def _is_attribute_free_br_element(
    node: _ComparisonElement | str | None,
) -> bool:
    return (
        isinstance(node, _ComparisonElement)
        and node.tag == "br"
        and node.attributes == ()
        and node.children == []
    )


def _has_inline_white_space_declaration(element: _ComparisonElement) -> bool:
    return any(
        key.lower() == "style"
        and (
            "/*" in value
            or "\\" in value
            or _INLINE_WHITE_SPACE_DECLARATION.search(value) is not None
        )
        for key, value in element.attributes
    )


def _canonical_comparison_element(
    element: _ComparisonElement,
    *,
    preserve_whitespace: bool = False,
) -> tuple[object, ...]:
    canonical_children: list[tuple[object, ...]] = []
    preserve_children = (
        preserve_whitespace
        or element.tag in {"pre", "textarea"}
        or _has_inline_white_space_declaration(element)
    )
    for index, child in enumerate(element.children):
        if isinstance(child, _ComparisonElement):
            canonical_children.append(
                _canonical_comparison_element(
                    child,
                    preserve_whitespace=preserve_children,
                )
            )
            continue
        if preserve_children:
            if child:
                canonical_children.append(("text", child))
            continue
        value = _HTML_ASCII_WHITESPACE_RUN.sub(" ", child)
        previous = _semantic_neighbor(element.children, index, -1)
        following = _semantic_neighbor(element.children, index, 1)
        if _is_html_ascii_whitespace(value):
            if _is_attribute_free_br_element(previous) or _is_attribute_free_br_element(
                following
            ):
                continue
            if (
                previous is None
                or following is None
                or _is_block_comparison_node(previous)
                or _is_block_comparison_node(following)
            ):
                continue
            canonical_children.append(("text", " "))
            continue
        if previous is None or _is_block_comparison_node(previous):
            value = value.lstrip(_HTML_ASCII_WHITESPACE)
        if following is None or _is_block_comparison_node(following):
            value = value.rstrip(_HTML_ASCII_WHITESPACE)
        canonical_children.append(("text", value))

    if element.tag == "table":
        normalized_table_children: list[tuple[object, ...]] = []
        direct_rows: list[tuple[object, ...]] = []

        def flush_direct_rows() -> None:
            if not direct_rows:
                return
            normalized_table_children.append(
                ("element", "tbody", (), tuple(direct_rows))
            )
            direct_rows.clear()

        for child in canonical_children:
            if _is_table_row_element(child):
                direct_rows.append(child)
            elif _is_attribute_free_table_section(child):
                direct_rows.extend(child[3])
            else:
                flush_direct_rows()
                normalized_table_children.append(child)
        flush_direct_rows()
        canonical_children = normalized_table_children
    if (
        element.tag in {"th", "td"}
        and len(canonical_children) == 1
        and len(canonical_children[0]) == 4
        and canonical_children[0][0] == "element"
        and canonical_children[0][1] == "p"
        and canonical_children[0][2] == ()
    ):
        canonical_children = list(canonical_children[0][3])
    return (
        "element",
        element.tag,
        element.attributes,
        tuple(canonical_children),
    )


def semantic_note_html_for_comparison(
    html_text: str,
) -> tuple[object, ...] | None:
    parser = _ComparisonHTMLParser()
    try:
        parser.feed(trim_note_html_for_comparison(html_text))
        parser.close()
    except Exception:
        return None
    meaningful_children = [
        child
        for child in parser.document.children
        if (
            not isinstance(child, str)
            or not _is_html_ascii_whitespace(child)
        )
    ]
    if (
        not parser.valid
        or len(meaningful_children) != 1
        or not isinstance(meaningful_children[0], _ComparisonElement)
    ):
        return None
    return _canonical_comparison_element(meaningful_children[0])


def note_html_matches_storage_semantics(left: str, right: str) -> bool:
    if trim_note_html_for_comparison(left) == trim_note_html_for_comparison(right):
        return True
    left_projection = semantic_note_html_for_comparison(left)
    return (
        left_projection is not None
        and left_projection == semantic_note_html_for_comparison(right)
    )


def first_matching_section(raw: str, names: tuple[str, ...]) -> str:
    for name in names:
        match = re.search(
            rf"<h2\b[^>]*>[^<]*{re.escape(name)}[^<]*</h2>(.*?)(?=<h2\b|</div>\s*$)",
            raw,
            flags=re.I | re.S,
        )
        if match:
            return match.group(1)
    return ""


def first_sentence(fragment: str, fallback: str) -> str:
    blockquote = re.search(r"<blockquote\b[^>]*>(.*?)</blockquote>", fragment, flags=re.I | re.S)
    candidate = blockquote.group(1) if blockquote else fragment
    list_item = re.search(r"<li\b[^>]*>(.*?)</li>", candidate, flags=re.I | re.S)
    if list_item:
        candidate = list_item.group(1)
    text = strip_tags(candidate) or fallback
    match = re.search(r"^(.+?[。！？])(?:\s|$)", text)
    return (match.group(1) if match else text)[:900]


def first_list_items(fragment: str, limit: int = 5) -> list[str]:
    items = [
        strip_tags(match)
        for match in re.findall(r"<li\b[^>]*>(.*?)</li>", fragment, flags=re.I | re.S)
    ]
    return [item for item in items if item][:limit]


def locate_source(raw: str) -> str:
    patterns = [
        (r"原文证据页：</strong>\s*([^<]+)", "PDF 页 "),
        (r"重点页：</strong>\s*([^<]+)", ""),
        (r"公式/原理来源页：</strong>\s*([^<]+)", ""),
        (r"原文核验[^：:]*[：:]\s*([^<]+)", ""),
        (r"(PDF\s*第\s*\d+(?:\s*[、,，\-–]\s*\d+)*\s*页)", ""),
    ]
    locators: list[str] = []
    for pattern, prefix in patterns:
        for match in re.findall(pattern, raw, flags=re.I):
            text = prefix + " ".join(html.unescape(match).split())
            if text and text not in locators:
                locators.append(text)
    if not locators:
        return "unresolved（既有笔记未提供可机器提取的精确定位）"
    return "；".join(locators[:3])


def creators_text(creators: object) -> str:
    if not isinstance(creators, list):
        return "unresolved"
    names: list[str] = []
    for creator in creators:
        if not isinstance(creator, dict):
            continue
        name = creator.get("name")
        if not name:
            name = " ".join(
                part for part in (creator.get("firstName"), creator.get("lastName")) if part
            )
        if name:
            names.append(str(name))
    return "；".join(names) or "unresolved"


def extract_year(date: object) -> str:
    match = re.search(r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b", str(date or ""))
    return match.group(1) if match else "unresolved"


def venue_text(data: dict[str, object]) -> str:
    for key in (
        "publicationTitle",
        "proceedingsTitle",
        "university",
        "publisher",
        "repository",
        "websiteTitle",
    ):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "unresolved"


def outer_inner(raw: str) -> str:
    match = re.match(
        r"\s*<div\b[^>]*data-schema-version=[\"'][^\"']+[\"'][^>]*>(.*)</div>\s*$",
        raw,
        flags=re.I | re.S,
    )
    inner = match.group(1) if match else raw
    inner = re.sub(r"<h1(\b[^>]*)>", r"<h3\1>", inner, flags=re.I)
    inner = re.sub(r"</h1>", "</h3>", inner, flags=re.I)
    inner = re.sub(r"<h2(\b[^>]*)>", r"<h3\1>", inner, flags=re.I)
    inner = re.sub(r"</h2>", "</h3>", inner, flags=re.I)
    replacements = {
        "Ẋ": "X 的时间导数",
        "Θ": "Theta",
        "Ξ": "Xi",
        "²": "^2",
        "³": "^3",
        "‖": "|",
    }
    for source, target in replacements.items():
        inner = inner.replace(source, target)
    return inner


def annotate_legacy_math(inner: str, locator: str) -> str:
    annotation = (
        "<p><strong>符号：</strong>沿用迁移前公式及其变量解释。"
        "<strong>作用：</strong>保留原笔记的方法关系。"
        "<strong>假设：</strong>本轮未重新推导，适用条件以原文和迁移前边界说明为准。"
        f"<strong>定位：</strong>{escape_text(locator)}。</p>"
    )
    return re.sub(
        r"(<pre\b[^>]*class=[\"'][^\"']*\bmath\b[^\"']*[\"'][^>]*>.*?</pre>)",
        lambda match: match.group(1) + annotation,
        inner,
        flags=re.I | re.S,
    )


def escape_text(text: str) -> str:
    return html.escape(text, quote=False)


def build_migrated_note(
    *,
    note_key: str,
    note_version: int,
    old_sha: str,
    parent_key: str,
    parent_data: dict[str, object],
    raw: str,
    pdf_path: str,
    pdf_sha: str,
    verified_at: str,
) -> str:
    title = str(parent_data.get("title") or "unresolved")
    doi_value = str(parent_data.get("DOI") or "").strip()
    url_value = str(parent_data.get("url") or "").strip()
    if re.match(r"^10\.\d{4,9}/", doi_value, flags=re.I):
        doi = doi_value
    elif re.match(r"^https?://", url_value, flags=re.I):
        doi = url_value
    else:
        doi = "unresolved"
    summary_fragment = first_matching_section(
        raw, ("论文摘要", "摘要", "先看全貌", "核心结论")
    )
    background_fragment = first_matching_section(
        raw, ("研究背景", "为什么值得研究", "论文摘要", "摘要")
    )
    method_fragment = first_matching_section(
        raw, ("方法一步一步", "方法", "输入和输出", "作者实际做了什么")
    )
    result_fragment = first_matching_section(
        raw, ("作者实际做了什么", "得到什么结果", "结果应该怎样读", "主要结果")
    )
    boundary_fragment = first_matching_section(
        raw, ("不能误读成什么", "局限", "边界", "适用范围")
    )
    relation_fragment = first_matching_section(
        raw, ("对终态形貌", "场景关系", "有什么用", "当前知识图")
    )

    conclusion = first_sentence(summary_fragment or raw, title)
    why = first_sentence(background_fragment or summary_fragment or raw, conclusion)
    method_items = first_list_items(method_fragment)
    mental_model = " → ".join(method_items[:5]) if method_items else (
        "研究问题 → 输入与假设 → 方法 → 原文证据 → 条件化结论"
    )
    result = first_sentence(result_fragment or summary_fragment or raw, conclusion)
    boundary = first_sentence(boundary_fragment or raw, "既有笔记未单列失败边界，需继续核验。")
    relation = first_sentence(
        relation_fragment or raw,
        "知识图归属待确认；具体依赖和冲突需在跨文献证据矩阵中维护。",
    )
    locator = locate_source(raw)

    claim_candidates = [conclusion, result, boundary]
    unique_claims: list[str] = []
    for claim in claim_candidates:
        if claim and claim not in unique_claims:
            unique_claims.append(claim)
    claim_rows = []
    for idx, claim in enumerate(unique_claims[:3], start=1):
        claim_rows.append(
            "<tr>"
            f"<td>C{idx}</td>"
            "<td>agent-inferred</td>"
            f"<td>{escape_text(claim)}</td>"
            f"<td>{escape_text(locator)}</td>"
            "<td>继承既有笔记的对象、数据制度与方法边界；本轮仅迁移格式。</td>"
            "<td>medium：由既有中文全文笔记与页码定位迁移，本轮未重新逐项阅读全文。</td>"
            "</tr>"
        )

    method_summary = "；".join(method_items) if method_items else (
        "输入、输出与关键步骤保留在下方迁移前详解中。"
    )
    old_inner = annotate_legacy_math(outer_inner(raw), locator)
    return f"""<div data-schema-version="9">
<h1>文献笔记｜{escape_text(title)}</h1>
<h2>资料与阅读状态</h2>
<p><strong>标题：</strong>{escape_text(title)}<br>
<strong>作者：</strong>{escape_text(creators_text(parent_data.get("creators")))}<br>
<strong>年份：</strong>{extract_year(parent_data.get("date"))}<br>
<strong>期刊或载体：</strong>{escape_text(venue_text(parent_data))}<br>
<strong>DOI或稳定标识：</strong>{escape_text(doi)}<br>
<strong>版本与出版状态：</strong>以 Zotero 父条目记录为准；本轮未重新核查更正或撤稿<br>
<strong>访问层级：</strong>{'full_text' if pdf_path != 'unresolved' else 'unresolved'}<br>
<strong>全文SHA-256：</strong>{pdf_sha}<br>
<strong>阅读深度：</strong>evidence<br>
<strong>核验时间：</strong>{verified_at}</p>
<h2>为什么重要</h2>
<p>{escape_text(why)}</p>
<h2>一句话结论</h2>
<p>{escape_text(conclusion)}</p>
<h2>心智模型</h2>
<p>{escape_text(mental_model)}</p>
<h2>关键主张与证据</h2>
<table>
<tr><th>Claim ID</th><th>性质</th><th>主张</th><th>证据与精确定位</th><th>条件</th><th>置信度与理由</th></tr>
{''.join(claim_rows)}
</table>
<h2>方法或推导</h2>
<p><strong>输入、输出与步骤：</strong>{escape_text(method_summary)}</p>
<p><strong>复现状态：</strong>本轮是既有笔记的结构迁移；公式、图表和实现细节仍以迁移前详解及原文为准。</p>
<h2>结果</h2>
<p>{escape_text(result)}</p>
<h2>假设、失败边界与竞争解释</h2>
<p>{escape_text(boundary)}</p>
<p>未在本轮重新阅读全文的结论均保持为中等置信度，不升级为新证据。</p>
<h2>知识图谱关系</h2>
<p>{escape_text(relation)}</p>
<p>共同上位链：结构发现 → 固定结构参数校准 → 可辨识性 → 不确定性与外部验证。</p>
<h2>复用</h2>
<p>可用于快速定位该来源的方法角色和适用边界；做研究决策或复现前，应按 Claim ID 回到原文定位复核。</p>
<h2>溯源</h2>
<p><strong>证据账本：</strong>由既有 Zotero 子笔记迁移，未另造来源陈述<br>
<strong>Zotero父条目：</strong>{parent_key}；<strong>迁移前笔记：</strong>{note_key}，version {note_version}<br>
<strong>迁移前笔记SHA-256：</strong>{old_sha}<br>
<strong>本地PDF：</strong>{escape_text(pdf_path)}<br>
<strong>SHA-256：</strong>{pdf_sha}<br>
<strong>Agent推断：</strong>已在关键主张表中显式标记；本轮未重新逐项阅读全文。</p>
<h2>附录：迁移前详解（内容与图像保留）</h2>
{old_inner}
</div>"""


def resolve_pdf(
    group_id: int,
    parent_key: str,
    children: list[dict[str, object]],
    *,
    selected_attachment_key: str | None = None,
) -> tuple[str, str, str | None, str | None]:
    candidates = [
        child
        for child in children
        if isinstance(child.get("data"), dict)
        and child["data"].get("itemType") == "attachment"
        and child["data"].get("contentType") == "application/pdf"
        and not child["data"].get("deleted")
    ]
    if not candidates:
        raise RuntimeError(
            f"{parent_key}: no live PDF attachment is available for source binding"
        )
    candidate_keys = sorted(str(candidate.get("key") or "") for candidate in candidates)
    if any(not ITEM_KEY_PATTERN.fullmatch(key) for key in candidate_keys):
        raise RuntimeError(f"{parent_key}: a PDF attachment key is invalid")
    if selected_attachment_key is None:
        if len(candidates) != 1:
            raise AmbiguousPDFAttachments(candidate_keys)
        attachment = candidates[0]
    else:
        matches = [
            candidate
            for candidate in candidates
            if candidate.get("key") == selected_attachment_key
        ]
        if len(matches) != 1:
            raise RuntimeError(
                f"{parent_key}: selected PDF attachment {selected_attachment_key} "
                "is not an unambiguous live PDF child"
            )
        attachment = matches[0]
    key = str(attachment.get("key"))
    attachment_data = attachment["data"]
    if attachment_data.get("parentItem") != parent_key:
        raise RuntimeError(f"{parent_key}: PDF attachment parent identity changed")
    link_mode = attachment_data.get("linkMode")
    if link_mode not in SUPPORTED_PDF_LINK_MODES:
        raise RuntimeError(
            f"{parent_key}: PDF attachment link mode is unsupported: {link_mode!r}"
        )
    try:
        file_url = get_text(f"/api/groups/{group_id}/items/{key}/file/view/url").strip()
    except Exception as exc:
        raise RuntimeError(
            f"{parent_key}: approved PDF attachment path lookup failed: {exc}"
        ) from exc
    parsed = urllib.parse.urlparse(file_url)
    if (
        parsed.scheme != "file"
        or parsed.netloc not in {"", "localhost"}
        or not parsed.path
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(
            f"{parent_key}: approved PDF attachment did not resolve to a local file URL"
        )
    try:
        path = Path(urllib.parse.unquote(parsed.path)).resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(
            f"{parent_key}: approved PDF attachment file is unavailable: {exc}"
        ) from exc
    if not path.is_file():
        raise RuntimeError(
            f"{parent_key}: approved PDF attachment path is not a regular file"
        )
    with path.open("rb") as stream:
        magic = stream.read(5)
    if magic != b"%PDF-":
        raise RuntimeError(
            f"{parent_key}: approved PDF attachment has invalid magic bytes"
        )
    return str(path), sha256_file(path), key, str(link_mode)


def prepare(args: argparse.Namespace) -> dict[str, object]:
    ensure_staging_destination(args.output_dir)
    projection_manifests = load_projection_manifests(
        getattr(args, "projection_manifest", None)
    )
    used_projection_html_sha256: set[str] = set()
    target = resolve_target_contract(
        args.group_id,
        args.collection_key,
        expected_collection_name=args.expected_collection_name,
    )

    parents = get_all_json(
        f"/api/groups/{args.group_id}/collections/"
        f"{args.collection_key}/items/top?include=data"
    )
    for index, parent in enumerate(parents):
        if not isinstance(parent, dict) or not isinstance(parent.get("data"), dict):
            raise RuntimeError(f"collection parent {index} is malformed")
        parent_key = parent.get("key")
        if (
            not isinstance(parent_key, str)
            or not ITEM_KEY_PATTERN.fullmatch(parent_key)
        ):
            raise RuntimeError(f"collection parent {index} has an invalid key")
        if parent["data"].get("itemType") in {
            "note",
            "attachment",
            "annotation",
        }:
            raise RuntimeError(
                f"collection parent {parent_key} is not a regular bibliographic item"
            )
        if parent["data"].get("parentItem"):
            raise RuntimeError(
                f"collection parent {parent_key} unexpectedly has a parent item"
            )
        if parent["data"].get("deleted"):
            raise RuntimeError(
                f"collection parent {parent_key} is deleted"
            )
    parent_keys = [str(parent["key"]) for parent in parents]
    if len(parent_keys) != len(set(parent_keys)):
        raise RuntimeError("collection item inventory contains duplicate keys")

    originals_dir = args.output_dir / "originals"
    updated_dir = args.output_dir / "updated"
    originals_dir.mkdir(mode=0o700)
    updated_dir.mkdir(mode=0o700)

    overrides: dict[str, str] = {}
    if args.override_map:
        data = json.loads(args.override_map.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("override map must be a JSON object of note_key -> HTML path")
        for raw_note_key, raw_html_path in data.items():
            note_key = str(raw_note_key)
            if not ITEM_KEY_PATTERN.fullmatch(note_key):
                raise ValueError("override map contains an invalid note key")
            if not isinstance(raw_html_path, str) or not raw_html_path.strip():
                raise ValueError(
                    f"{note_key}: override HTML path must be a nonempty string"
                )
            overrides[note_key] = raw_html_path

    parent_note_paths: dict[str, Path] = {}
    parent_note_map = getattr(args, "parent_note_map", None)
    if parent_note_map:
        data = json.loads(parent_note_map.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(
                "parent note map must be a JSON object of parent_key -> schema-9 HTML path"
            )
        for raw_parent_key, raw_html_path in data.items():
            parent_key = str(raw_parent_key)
            if not ITEM_KEY_PATTERN.fullmatch(parent_key):
                raise ValueError("parent note map contains an invalid parent key")
            if not isinstance(raw_html_path, str) or not raw_html_path.strip():
                raise ValueError(
                    f"{parent_key}: parent note HTML path must be a nonempty string"
                )
            html_path = Path(raw_html_path).expanduser()
            if not html_path.is_absolute():
                raise ValueError(
                    f"{parent_key}: parent note HTML path must be absolute"
                )
            try:
                html_path = html_path.resolve(strict=True)
            except OSError as exc:
                raise ValueError(
                    f"{parent_key}: parent note HTML path is unavailable: {exc}"
                ) from exc
            if not html_path.is_file():
                raise ValueError(
                    f"{parent_key}: parent note HTML path is not a regular file"
                )
            parent_note_paths[parent_key] = html_path
    unknown_parent_note_keys = set(parent_note_paths) - set(parent_keys)
    if unknown_parent_note_keys:
        raise ValueError(
            "parent note map contains parents outside the collection: "
            f"{sorted(unknown_parent_note_keys)}"
        )

    pdf_selectors: dict[str, str] = {}
    pdf_attachment_map = getattr(args, "pdf_attachment_map", None)
    if pdf_attachment_map:
        data = json.loads(pdf_attachment_map.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(
                "PDF attachment map must be a JSON object of parent_key -> attachment_key"
            )
        for raw_parent_key, raw_attachment_key in data.items():
            parent_key = str(raw_parent_key)
            attachment_key = str(raw_attachment_key)
            if (
                not ITEM_KEY_PATTERN.fullmatch(parent_key)
                or not ITEM_KEY_PATTERN.fullmatch(attachment_key)
            ):
                raise ValueError("PDF attachment map contains an invalid item key")
            pdf_selectors[parent_key] = attachment_key
    unknown_selector_parents = set(pdf_selectors) - set(parent_keys)
    if unknown_selector_parents:
        raise ValueError(
            "PDF attachment map contains parents outside the collection: "
            f"{sorted(unknown_selector_parents)}"
        )

    entries: list[dict[str, object]] = []
    used_pdf_selectors: set[str] = set()
    used_overrides: set[str] = set()
    used_parent_notes: set[str] = set()
    verified_at = datetime.now().astimezone().isoformat(timespec="seconds")
    for parent in parents:
        parent_key = str(parent.get("key"))
        parent_data = parent["data"]
        children = get_all_json(
            f"/api/groups/{args.group_id}/items/{parent_key}/children?include=data"
        )
        for index, child in enumerate(children):
            if not isinstance(child, dict) or not isinstance(child.get("data"), dict):
                raise RuntimeError(f"{parent_key}: child {index} is malformed")
            child_key = child.get("key")
            if (
                not isinstance(child_key, str)
                or not ITEM_KEY_PATTERN.fullmatch(child_key)
            ):
                raise RuntimeError(f"{parent_key}: child {index} has an invalid key")
            if child["data"].get("parentItem") != parent_key:
                raise RuntimeError(
                    f"{parent_key}: child {child_key} has a different parent"
                )
            if child["data"].get("deleted"):
                raise RuntimeError(
                    f"{parent_key}: child {child_key} is deleted"
                )
        child_keys = [str(child["key"]) for child in children]
        if len(child_keys) != len(set(child_keys)):
            raise RuntimeError(f"{parent_key}: child inventory contains duplicate keys")
        notes = [
            child
            for child in children
            if isinstance(child.get("data"), dict) and child["data"].get("itemType") == "note"
        ]
        child_note_inventory = sorted(str(note["key"]) for note in notes)
        child_attachment_inventory = sorted(
            str(child["key"])
            for child in children
            if child["data"].get("itemType") == "attachment"
        )
        common_entry = {
            "parent_key": parent_key,
            "title": parent_data.get("title"),
            "child_item_inventory": sorted(child_keys),
            "child_note_inventory": child_note_inventory,
            "child_attachment_inventory": child_attachment_inventory,
        }
        selected_attachment_key = pdf_selectors.get(parent_key)
        if selected_attachment_key:
            used_pdf_selectors.add(parent_key)
        try:
            pdf_path, pdf_sha, attachment_key, attachment_link_mode = resolve_pdf(
                args.group_id,
                parent_key,
                children,
                selected_attachment_key=selected_attachment_key,
            )
        except AmbiguousPDFAttachments as exc:
            entries.append(
                {
                    **common_entry,
                    "status": "blocked_multiple_pdfs",
                    "pdf_attachment_candidates": exc.keys,
                }
            )
            if parent_key in parent_note_paths:
                used_parent_notes.add(parent_key)
            continue

        pdf_binding = {
            "pdf_attachment_key": attachment_key,
            "pdf_attachment_link_mode": attachment_link_mode,
            "pdf_path": pdf_path,
            "pdf_sha256": pdf_sha,
        }
        if not notes:
            if parent_key not in parent_note_paths:
                entries.append(
                    {
                        **common_entry,
                        **pdf_binding,
                        "status": "no_existing_note",
                    }
                )
                continue
            used_parent_notes.add(parent_key)
            parent_version = parent.get("version")
            if type(parent_version) is not int or parent_version <= 0:
                raise RuntimeError(
                    f"{parent_key}: parent version is invalid for note creation"
                )
            if (
                parent_data.get("key") != parent_key
                or parent_data.get("version") != parent_version
            ):
                raise RuntimeError(
                    f"{parent_key}: parent wrapper and item data identity differ"
                )
            requested_html = parent_note_paths[parent_key].read_text(encoding="utf-8")
            projection_fields = projection_binding_for_html(
                requested_html,
                parent_note_paths[parent_key],
                projection_manifests,
                used_projection_html_sha256,
            )
            new_path = updated_dir / f"{parent_key}.create.html"
            write_text_exclusive(new_path, requested_html)
            new_sha = sha256_file(new_path)
            errors, warnings, validation_summary = validate_note(requested_html)
            entries.append(
                {
                    **common_entry,
                    **pdf_binding,
                    "doi": parent_data.get("DOI"),
                    "expected_parent_key": parent_key,
                    "parent_version": parent_version,
                    "parent_data_snapshot_schema": PARENT_DATA_SNAPSHOT_SCHEMA,
                    "parent_data_snapshot_sha256": (
                        parent_data_snapshot_sha256(parent_data)
                    ),
                    "new_path": str(new_path),
                    "new_sha256": new_sha,
                    "migration_kind": "parent_note_create",
                    "status": "create_verified" if not errors else "staged_invalid",
                    "validation_errors": errors,
                    "validation_warnings": warnings,
                    "validation_summary": validation_summary,
                    **projection_fields,
                }
            )
            continue
        if len(notes) != 1:
            if parent_key in parent_note_paths:
                used_parent_notes.add(parent_key)
            entries.append(
                {
                    **common_entry,
                    **pdf_binding,
                    "status": "blocked_multiple_notes",
                    "note_count": len(notes),
                }
            )
            continue
        note = notes[0]
        note_key = str(note.get("key"))
        note_data = note["data"]
        raw = str(note_data.get("note") or "")
        old_bytes = raw.encode("utf-8")
        old_sha = sha256_bytes(old_bytes)
        old_path = originals_dir / f"{note_key}.html"
        write_bytes_exclusive(old_path, old_bytes)
        projection_fields: dict[str, object] = {}

        if parent_key in parent_note_paths and note_key in overrides:
            raise ValueError(
                f"{parent_key}: parent note map and override map both target {note_key}"
            )
        if parent_key in parent_note_paths:
            used_parent_notes.add(parent_key)
            projection_source_path = parent_note_paths[parent_key]
            override_html = projection_source_path.read_text(encoding="utf-8")
            projection_fields = projection_binding_for_html(
                override_html,
                projection_source_path,
                projection_manifests,
                used_projection_html_sha256,
            )
            migration_kind = "curated_parent_override"
            if note_html_matches_storage_semantics(override_html, raw):
                migrated = raw
                staged_status = "unchanged_verified"
            else:
                migrated = override_html
                staged_status = "staged_verified"
        elif note_key in overrides:
            used_overrides.add(note_key)
            override_path = Path(overrides[note_key]).expanduser().resolve()
            override_html = override_path.read_text(encoding="utf-8")
            projection_fields = projection_binding_for_html(
                override_html,
                override_path,
                projection_manifests,
                used_projection_html_sha256,
            )
            migration_kind = "curated_override"
            if note_html_matches_storage_semantics(override_html, raw):
                migrated = raw
                staged_status = "unchanged_verified"
            else:
                migrated = override_html
                staged_status = "staged_verified"
        else:
            existing_errors, _existing_warnings, existing_summary = validate_note(raw)
            if (
                not existing_errors
                and str(existing_summary.get("schema_version")) == "9"
            ):
                migrated = raw
                migration_kind = "existing_schema9"
                staged_status = "unchanged_verified"
            else:
                migrated = build_migrated_note(
                    note_key=note_key,
                    note_version=int(note.get("version") or 0),
                    old_sha=old_sha,
                    parent_key=parent_key,
                    parent_data=parent_data,
                    raw=raw,
                    pdf_path=pdf_path,
                    pdf_sha=pdf_sha,
                    verified_at=verified_at,
                )
                migration_kind = "structure_preserving_wrapper"
                staged_status = "staged_verified"

        new_path = updated_dir / f"{note_key}.html"
        write_text_exclusive(new_path, migrated)
        new_sha = sha256_file(new_path)
        errors, warnings, validation_summary = validate_note(migrated)
        status = (
            staged_status
            if not errors
            else "staged_invalid"
        )
        entries.append(
            {
                **common_entry,
                "doi": parent_data.get("DOI"),
                "note_key": note_key,
                "note_version": note.get("version"),
                "expected_parent_key": parent_key,
                "old_path": str(old_path),
                "old_sha256": old_sha,
                "new_path": str(new_path),
                "new_sha256": new_sha,
                **pdf_binding,
                "migration_kind": migration_kind,
                "status": status,
                "validation_errors": errors,
                "validation_warnings": warnings,
                "validation_summary": validation_summary,
                **projection_fields,
            }
        )

    unused_pdf_selectors = set(pdf_selectors) - used_pdf_selectors
    if unused_pdf_selectors:
        raise ValueError(
            "PDF attachment map entries were not used by a live collection parent: "
            f"{sorted(unused_pdf_selectors)}"
        )
    unused_overrides = set(overrides) - used_overrides
    if unused_overrides:
        raise ValueError(
            "override map entries were not used by an eligible single-note target: "
            f"{sorted(unused_overrides)}"
        )
    unused_parent_notes = set(parent_note_paths) - used_parent_notes
    if unused_parent_notes:
        raise ValueError(
            "parent note map entries were not used by an eligible target: "
            f"{sorted(unused_parent_notes)}"
        )
    unused_projection_manifests = (
        set(projection_manifests) - used_projection_html_sha256
    )
    if unused_projection_manifests:
        raise ValueError(
            "projection manifests were not used by an eligible projected note: "
            f"{sorted(unused_projection_manifests)}"
        )

    return {
        "manifest_version": "2",
        "generated_at": verified_at,
        "write_performed": False,
        "target": target,
        "collection_item_inventory": sorted(
            parent_keys
        ),
        "entries": entries,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group-id", type=int, required=True)
    parser.add_argument("--collection-key", required=True)
    parser.add_argument("--expected-collection-name")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--override-map", type=Path)
    parser.add_argument(
        "--parent-note-map",
        type=Path,
        help=(
            "JSON object mapping parent item keys to absolute schema-9 HTML paths; "
            "creates a child note when none exists or acts as a curated override "
            "when exactly one exists"
        ),
    )
    parser.add_argument(
        "--pdf-attachment-map",
        type=Path,
        help="JSON object mapping parent item keys to explicitly approved PDF attachment keys",
    )
    parser.add_argument(
        "--projection-manifest",
        action="append",
        type=Path,
        help=(
            "absolute PaperKnowledgeNoteProjection/v1 path; repeat for each "
            "PaperKnowledgeNote/v2 HTML supplied through a note map"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir = args.output_dir.expanduser().resolve()
    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        manifest = prepare(args)
    except Exception as exc:
        print(f"migration staging failed: {exc}", file=sys.stderr)
        return 2
    manifest_path = args.output_dir / "migration_manifest.json"
    write_text_exclusive(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )
    staged = sum(
        1 for entry in manifest["entries"] if entry.get("status") == "staged_verified"
    )
    created = sum(
        1 for entry in manifest["entries"] if entry.get("status") == "create_verified"
    )
    invalid = sum(
        1 for entry in manifest["entries"] if entry.get("status") == "staged_invalid"
    )
    unchanged = sum(
        1
        for entry in manifest["entries"]
        if entry.get("status") == "unchanged_verified"
    )
    blocked_notes = sum(
        1
        for entry in manifest["entries"]
        if entry.get("status") == "blocked_multiple_notes"
    )
    blocked_pdfs = sum(
        1
        for entry in manifest["entries"]
        if entry.get("status") == "blocked_multiple_pdfs"
    )
    without_note = sum(
        1
        for entry in manifest["entries"]
        if entry.get("status") == "no_existing_note"
    )
    print(
        json.dumps(
            {
                "manifest": str(manifest_path),
                "staged_verified": staged,
                "create_verified": created,
                "unchanged_verified": unchanged,
                "staged_invalid": invalid,
                "blocked_multiple_notes": blocked_notes,
                "blocked_multiple_pdfs": blocked_pdfs,
                "no_existing_note": without_note,
                "total_entries": len(manifest["entries"]),
                "write_performed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if invalid == 0 and blocked_notes == 0 and blocked_pdfs == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
