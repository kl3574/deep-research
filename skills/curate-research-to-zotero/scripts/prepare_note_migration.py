#!/usr/bin/env python3
"""Stage non-destructive schema-9 migrations for existing Zotero child notes.

The script reads Zotero's local API, writes original and migrated HTML files to
an external staging directory, and records hashes and validation results. It
never writes to Zotero.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from verify_note_html import validate_note


BASE_URL = "http://127.0.0.1:23119"


def get_json(path: str) -> object:
    with urllib.request.urlopen(BASE_URL + path, timeout=20) as response:
        return json.load(response)


def get_text(path: str) -> str:
    with urllib.request.urlopen(BASE_URL + path, timeout=20) as response:
        return response.read().decode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def strip_tags(fragment: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", fragment, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(html.unescape(text).split())


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
        "位于PRIVATE_ZOTERO_TARGET知识图中；具体依赖和冲突需在跨文献证据矩阵中维护。",
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


def resolve_pdf(group_id: int, children: list[dict[str, object]]) -> tuple[str, str, str | None]:
    candidates = [
        child
        for child in children
        if isinstance(child.get("data"), dict)
        and child["data"].get("itemType") == "attachment"
        and child["data"].get("contentType") == "application/pdf"
    ]
    if not candidates:
        return "unresolved", "unresolved", None
    attachment = candidates[0]
    key = str(attachment.get("key"))
    try:
        file_url = get_text(f"/api/groups/{group_id}/items/{key}/file/view/url").strip()
        parsed = urllib.parse.urlparse(file_url)
        path = Path(urllib.parse.unquote(parsed.path))
        if parsed.scheme != "file" or not path.is_file():
            return str(path), "unresolved", key
        return str(path), sha256_file(path), key
    except Exception:
        return "unresolved", "unresolved", key


def prepare(args: argparse.Namespace) -> dict[str, object]:
    collection = get_json(f"/api/groups/{args.group_id}/collections/{args.collection_key}")
    if not isinstance(collection, dict):
        raise RuntimeError("collection response was not an object")
    collection_data = collection.get("data")
    if not isinstance(collection_data, dict):
        raise RuntimeError("collection data missing")
    if args.expected_collection_name and collection_data.get("name") != args.expected_collection_name:
        raise RuntimeError(
            f"collection name mismatch: {collection_data.get('name')!r} != {args.expected_collection_name!r}"
        )

    parents = get_json(
        f"/api/groups/{args.group_id}/collections/{args.collection_key}/items/top?limit=100&include=data"
    )
    if not isinstance(parents, list):
        raise RuntimeError("collection item response was not an array")

    originals_dir = args.output_dir / "originals"
    updated_dir = args.output_dir / "updated"
    originals_dir.mkdir(parents=True, exist_ok=True)
    updated_dir.mkdir(parents=True, exist_ok=True)

    overrides: dict[str, str] = {}
    if args.override_map:
        data = json.loads(args.override_map.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("override map must be a JSON object of note_key -> HTML path")
        overrides = {str(key): str(value) for key, value in data.items()}

    entries: list[dict[str, object]] = []
    verified_at = datetime.now().astimezone().isoformat(timespec="seconds")
    for parent in parents:
        if not isinstance(parent, dict) or not isinstance(parent.get("data"), dict):
            continue
        parent_key = str(parent.get("key"))
        parent_data = parent["data"]
        children = get_json(
            f"/api/groups/{args.group_id}/items/{parent_key}/children?limit=100&include=data"
        )
        if not isinstance(children, list):
            continue
        notes = [
            child
            for child in children
            if isinstance(child.get("data"), dict) and child["data"].get("itemType") == "note"
        ]
        if not notes:
            entries.append(
                {
                    "parent_key": parent_key,
                    "title": parent_data.get("title"),
                    "status": "no_existing_note",
                }
            )
            continue
        if len(notes) != 1:
            entries.append(
                {
                    "parent_key": parent_key,
                    "title": parent_data.get("title"),
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
        old_path.write_bytes(old_bytes)
        pdf_path, pdf_sha, attachment_key = resolve_pdf(args.group_id, children)

        if note_key in overrides:
            override_path = Path(overrides[note_key]).expanduser().resolve()
            migrated = override_path.read_text(encoding="utf-8")
            migration_kind = "curated_override"
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

        new_path = updated_dir / f"{note_key}.html"
        new_path.write_text(migrated, encoding="utf-8")
        new_sha = sha256_file(new_path)
        errors, warnings, validation_summary = validate_note(migrated)
        entries.append(
            {
                "parent_key": parent_key,
                "title": parent_data.get("title"),
                "doi": parent_data.get("DOI"),
                "note_key": note_key,
                "note_version": note.get("version"),
                "expected_parent_key": parent_key,
                "old_path": str(old_path),
                "old_sha256": old_sha,
                "new_path": str(new_path),
                "new_sha256": new_sha,
                "pdf_attachment_key": attachment_key,
                "pdf_path": pdf_path,
                "pdf_sha256": pdf_sha,
                "migration_kind": migration_kind,
                "status": "staged_verified" if not errors else "staged_invalid",
                "validation_errors": errors,
                "validation_warnings": warnings,
                "validation_summary": validation_summary,
            }
        )

    return {
        "manifest_version": "1",
        "generated_at": verified_at,
        "write_performed": False,
        "target": {
            "group_id": args.group_id,
            "collection_key": args.collection_key,
            "collection_name": collection_data.get("name"),
            "collection_version": collection.get("version"),
        },
        "entries": entries,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group-id", type=int, required=True)
    parser.add_argument("--collection-key", required=True)
    parser.add_argument("--expected-collection-name")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--override-map", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir = args.output_dir.expanduser().resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    try:
        manifest = prepare(args)
    except Exception as exc:
        print(f"migration staging failed: {exc}", file=sys.stderr)
        return 2
    manifest_path = args.output_dir / "migration_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    staged = sum(
        1 for entry in manifest["entries"] if entry.get("status") == "staged_verified"
    )
    invalid = sum(
        1 for entry in manifest["entries"] if entry.get("status") == "staged_invalid"
    )
    print(
        json.dumps(
            {
                "manifest": str(manifest_path),
                "staged_verified": staged,
                "staged_invalid": invalid,
                "total_entries": len(manifest["entries"]),
                "write_performed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if invalid == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
