import copy
import unittest

from paper_understanding_route import (
    ContractError,
    build_validation_binding,
    canonical_route_digest,
    validate_paper_understanding_route,
)


def route_fixture():
    understanding_binding = {
        "understanding_id": "paper-understanding-aaaaaaaaaaaaaaaa",
        "understanding_digest": "a" * 64,
        "validation_record_id": "paper-understanding-validation-bbbbbbbbbbbbbbbb",
        "validation_record_digest": "b" * 64,
    }
    projection_ref = {
        "schema": "UnderstandingNetworkProjection/v1",
        "projection_id": "understanding-projection-cccccccccccccccc",
        "projection_digest": "c" * 64,
    }
    route = {
        "schema": "PaperUnderstandingRoute/v1",
        "schema_version": "1.0",
        "route_id": "",
        "route_digest": "",
        "understanding_binding": understanding_binding,
        "projection_ref": projection_ref,
        "validation_binding": build_validation_binding(
            understanding_binding, projection_ref
        ),
        "destinations": ["research-knowledge-network", "network-gap-discovery"],
        "orchestration_only": True,
        "semantic_rewrite_allowed": False,
    }
    route["route_digest"] = canonical_route_digest(route)
    route["route_id"] = f"understanding-route-{route['route_digest'][:16]}"
    return route


def rehash_route(route):
    route["route_digest"] = canonical_route_digest(route)
    route["route_id"] = f"understanding-route-{route['route_digest'][:16]}"
    return route


class PaperUnderstandingRouteTest(unittest.TestCase):
    def test_accepts_content_addressed_orchestration_only_route(self):
        route = route_fixture()
        self.assertIs(validate_paper_understanding_route(route), route)

    def test_rejects_semantic_rewrite_or_unknown_destination(self):
        rewrite = copy.deepcopy(route_fixture())
        rewrite["semantic_rewrite_allowed"] = True
        rehash_route(rewrite)
        with self.assertRaisesRegex(ContractError, "semantic_rewrite_allowed"):
            validate_paper_understanding_route(rewrite)

        unknown = copy.deepcopy(route_fixture())
        unknown["destinations"] = ["scholar-discovery"]
        rehash_route(unknown)
        with self.assertRaisesRegex(ContractError, "destinations"):
            validate_paper_understanding_route(unknown)

    def test_validation_binding_binds_record_artifact_and_projection(self):
        tampered = route_fixture()
        tampered["projection_ref"]["projection_digest"] = "d" * 64
        tampered["projection_ref"]["projection_id"] = (
            "understanding-projection-dddddddddddddddd"
        )
        rehash_route(tampered)
        with self.assertRaisesRegex(ContractError, "validation_binding must content-bind"):
            validate_paper_understanding_route(tampered)

    def test_recomputed_outer_digest_cannot_hide_arbitrary_upstream_ids(self):
        arbitrary_understanding = route_fixture()
        arbitrary_understanding["understanding_binding"]["understanding_id"] = (
            "paper-understanding-arbitrary"
        )
        arbitrary_understanding["validation_binding"]["understanding_id"] = (
            "paper-understanding-arbitrary"
        )
        rehash_route(arbitrary_understanding)
        with self.assertRaisesRegex(ContractError, "understanding_id does not match"):
            validate_paper_understanding_route(arbitrary_understanding)

        arbitrary_projection = route_fixture()
        arbitrary_projection["projection_ref"]["projection_id"] = (
            "understanding-projection-arbitrary"
        )
        arbitrary_projection["validation_binding"]["projection_id"] = (
            "understanding-projection-arbitrary"
        )
        rehash_route(arbitrary_projection)
        with self.assertRaisesRegex(ContractError, "projection_id does not match"):
            validate_paper_understanding_route(arbitrary_projection)

        arbitrary_validator = route_fixture()
        arbitrary_validator["understanding_binding"]["validation_record_id"] = (
            "paper-understanding-validation-arbitrary"
        )
        arbitrary_validator["validation_binding"]["validation_record_id"] = (
            "paper-understanding-validation-arbitrary"
        )
        rehash_route(arbitrary_validator)
        with self.assertRaisesRegex(ContractError, "validation_record_id does not match"):
            validate_paper_understanding_route(arbitrary_validator)


if __name__ == "__main__":
    unittest.main()
