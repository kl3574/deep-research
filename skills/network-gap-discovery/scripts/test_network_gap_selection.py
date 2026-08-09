import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from network_gap_discovery import (
    ContractError,
    REVIEWED_GAP_SELECTION_SCHEMA,
    emit_search_requests,
    generate_hypotheses_from_probe,
    prioritize,
    scan_network,
    select_hypotheses,
    sha256_json,
    validate_hypotheses,
    write_json,
)
from test_network_gap_discovery import doe_surrogate_noise_network_fixture


SCRIPT = Path(__file__).with_name("network_gap_discovery.py")


def prioritized_fixture():
    network = doe_surrogate_noise_network_fixture(
        single_source_count=3, isolate_count=1
    )
    hypotheses = generate_hypotheses_from_probe(scan_network(network), network)
    prioritized = prioritize(hypotheses, network)
    return network, prioritized


def reviewed_selection(prioritized, selected_ids):
    return {
        "schema": REVIEWED_GAP_SELECTION_SCHEMA,
        "input_ref": {
            "schema": "KnowledgeGapHypotheses/v1",
            "sha256": sha256_json(prioritized),
        },
        "network_ref": copy.deepcopy(prioritized["network_ref"]),
        "round_id": prioritized["round_id"],
        "selected_hypothesis_ids": selected_ids,
        "review_status": "approved",
    }


class ReviewedGapSelectionTests(unittest.TestCase):
    def test_cli_preserves_all_candidates_and_emits_reviewed_subset(self):
        network, prioritized = prioritized_fixture()
        eligible = [
            row["hypothesis_id"]
            for row in prioritized["hypotheses"]
            if row["status"] == "selected"
        ]
        selected_ids = eligible[:2]
        decision = reviewed_selection(prioritized, selected_ids)

        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            os.chmod(directory, 0o700)
            network_path = directory / "network.export.json"
            input_path = directory / "prioritized.json"
            decision_path = directory / "selection.json"
            output_path = directory / "selected-only.json"
            for path, value in (
                (network_path, network),
                (input_path, prioritized),
                (decision_path, decision),
            ):
                path.write_text(json.dumps(value), encoding="utf-8")
                os.chmod(path, 0o600)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "select",
                    "--input",
                    str(input_path),
                    "--selection",
                    str(decision_path),
                    "--network",
                    str(network_path),
                    "--output",
                    str(output_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            output = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(len(output["hypotheses"]), len(prioritized["hypotheses"]))
        self.assertEqual(
            output["selection_summary"]["selected_hypothesis_ids"], selected_ids
        )
        self.assertEqual(
            output["selection_summary"]["unselected_proposed_hypothesis_ids"],
            [
                row["hypothesis_id"]
                for row in output["hypotheses"]
                if row["hypothesis_id"] not in selected_ids
            ],
        )
        self.assertTrue(
            all(
                row["status"] == "proposed"
                for row in output["hypotheses"]
                if row["hypothesis_id"] not in selected_ids
            )
        )
        validate_hypotheses(output, network)
        request_set = emit_search_requests(output, network)
        self.assertEqual(request_set["selected_hypothesis_ids"], selected_ids)
        self.assertEqual(
            request_set["reviewed_selection_ref"], output["reviewed_selection_ref"]
        )

    def test_rejects_unknown_duplicate_and_structural_ids(self):
        network, prioritized = prioritized_fixture()
        eligible_id = next(
            row["hypothesis_id"]
            for row in prioritized["hypotheses"]
            if row["status"] == "selected"
        )
        structural_id = next(
            row["hypothesis_id"]
            for row in prioritized["hypotheses"]
            if row.get("structural_only")
        )
        cases = (
            (["KGH-UNKNOWN"], "unknown hypothesis"),
            ([eligible_id, eligible_id], "must be unique"),
            ([structural_id], "structural hypothesis"),
        )
        for selected_ids, message in cases:
            with self.subTest(selected_ids=selected_ids):
                with self.assertRaisesRegex(ContractError, message):
                    select_hypotheses(
                        prioritized,
                        reviewed_selection(prioritized, selected_ids),
                        network,
                    )

    def test_rejects_input_schema_and_digest_mismatch(self):
        network, prioritized = prioritized_fixture()
        selected_id = next(
            row["hypothesis_id"]
            for row in prioritized["hypotheses"]
            if row["status"] == "selected"
        )
        for field, value, message in (
            ("schema", "Wrong/v1", "input schema"),
            ("sha256", "0" * 64, "input digest mismatch"),
        ):
            with self.subTest(field=field):
                decision = reviewed_selection(prioritized, [selected_id])
                decision["input_ref"][field] = value
                with self.assertRaisesRegex(ContractError, message):
                    select_hypotheses(prioritized, decision, network)

    def test_rejects_direct_status_edit_even_when_manifest_is_rehashed(self):
        network, prioritized = prioritized_fixture()
        tampered = copy.deepcopy(prioritized)
        row = next(
            row for row in tampered["hypotheses"] if row["status"] == "selected"
        )
        row["status"] = "proposed"
        tampered["selection_summary"] = {
            "selected_count": len(
                [row for row in tampered["hypotheses"] if row["status"] == "selected"]
            ),
            "selected_hypothesis_ids": [
                row["hypothesis_id"]
                for row in tampered["hypotheses"]
                if row["status"] == "selected"
            ],
            "unselected_proposed_hypothesis_ids": [
                row["hypothesis_id"]
                for row in tampered["hypotheses"]
                if row["status"] == "proposed"
            ],
        }
        decision = reviewed_selection(tampered, [])
        with self.assertRaisesRegex(ContractError, "manually changed"):
            select_hypotheses(tampered, decision, network)

    def test_empty_allowlist_is_valid_and_select_output_cannot_be_reselected(self):
        network, prioritized = prioritized_fixture()
        output = select_hypotheses(
            prioritized, reviewed_selection(prioritized, []), network
        )
        self.assertEqual(output["selection_summary"]["selected_count"], 0)
        self.assertTrue(
            all(row["status"] == "proposed" for row in output["hypotheses"])
        )
        with self.assertRaisesRegex(ContractError, "zero selected hypotheses"):
            emit_search_requests(output, network)
        with self.assertRaisesRegex(ContractError, "prior selection output"):
            select_hypotheses(output, reviewed_selection(output, []), network)

    def test_emitter_rejects_direct_prioritize_and_tampered_review_ref(self):
        network, prioritized = prioritized_fixture()
        with self.assertRaisesRegex(ContractError, "reviewed_selection_ref"):
            emit_search_requests(prioritized, network)

        fabricated = copy.deepcopy(prioritized)
        fabricated_ids = fabricated["selection_summary"]["selected_hypothesis_ids"]
        fabricated["reviewed_selection_ref"] = {
            "schema": REVIEWED_GAP_SELECTION_SCHEMA,
            "sha256": "a" * 64,
            "input_sha256": "b" * 64,
            "selected_hypothesis_ids": fabricated_ids,
            "review_status": "approved",
        }
        with self.assertRaisesRegex(ContractError, "input digest"):
            emit_search_requests(fabricated, network)

        selected_id = next(
            row["hypothesis_id"]
            for row in prioritized["hypotheses"]
            if row["status"] == "selected"
        )
        output = select_hypotheses(
            prioritized, reviewed_selection(prioritized, [selected_id]), network
        )
        output["reviewed_selection_ref"]["selected_hypothesis_ids"] = []
        with self.assertRaisesRegex(ContractError, "match selected hypotheses"):
            emit_search_requests(output, network)

        output = select_hypotheses(
            prioritized, reviewed_selection(prioritized, [selected_id]), network
        )
        output["reviewed_selection_ref"]["sha256"] = "f" * 64
        with self.assertRaisesRegex(ContractError, "selection reference digest"):
            emit_search_requests(output, network)

    def test_emitter_rejects_incomplete_or_mutated_selection_projection(self):
        network, prioritized = prioritized_fixture()
        selected_id = next(
            row["hypothesis_id"]
            for row in prioritized["hypotheses"]
            if row["status"] == "selected"
        )
        baseline = select_hypotheses(
            prioritized, reviewed_selection(prioritized, [selected_id]), network
        )
        unselected_id = next(
            row["hypothesis_id"]
            for row in baseline["hypotheses"]
            if row["hypothesis_id"] != selected_id
        )

        def lifecycle(status):
            def mutate(value):
                row = next(
                    row
                    for row in value["hypotheses"]
                    if row["hypothesis_id"] == unselected_id
                )
                row["status"] = status
                value["selection_summary"][
                    "unselected_proposed_hypothesis_ids"
                ].remove(unselected_id)

            return mutate

        def delete(value):
            value["hypotheses"] = [
                row
                for row in value["hypotheses"]
                if row["hypothesis_id"] != unselected_id
            ]
            value["selection_summary"][
                "unselected_proposed_hypothesis_ids"
            ].remove(unselected_id)

        def insert(value):
            row = copy.deepcopy(
                next(
                    row
                    for row in value["hypotheses"]
                    if row["hypothesis_id"] == unselected_id
                )
            )
            row["hypothesis_id"] = "KGH-EXTRA"
            value["hypotheses"].append(row)
            value["selection_summary"][
                "unselected_proposed_hypothesis_ids"
            ].append("KGH-EXTRA")

        def mutate_content(value):
            row = next(
                row
                for row in value["hypotheses"]
                if row["hypothesis_id"] == unselected_id
            )
            row["hypothesis"] = "Mutated after reviewed selection"

        cases = {
            "no_signal": lifecycle("no_signal"),
            "blocked": lifecycle("blocked"),
            "delete": delete,
            "extra": insert,
            "mutate": mutate_content,
        }
        for label, mutate in cases.items():
            with self.subTest(label=label):
                value = copy.deepcopy(baseline)
                mutate(value)
                with self.assertRaises(ContractError):
                    emit_search_requests(value, network)

    def test_private_writer_cleans_temporary_on_base_exception(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            os.chmod(root, 0o700)
            target = root / "selected.json"
            target.write_text("old\n", encoding="utf-8")
            os.chmod(target, 0o600)
            with mock.patch(
                "network_gap_discovery.os.replace",
                side_effect=KeyboardInterrupt("injected interruption"),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    write_json(target, {"new": True})
            self.assertEqual(target.read_text(encoding="utf-8"), "old\n")
            self.assertEqual(list(root.glob(".selected.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
