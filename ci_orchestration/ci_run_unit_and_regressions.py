#!/usr/bin/env python3
"""Run Signalpost package smoke, core Python 3.12.15 unit discovery, and supplemental Node5 validation (CI-V1-02/03/05)."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

# Exact 30 root Python modules from SIGNALPOST-CI-EXACT-PRODUCT-DTO-DATA-20261111.json and Dockerfile
EXPECTED_ROOT_MODULES = [
    "agent",
    "attribution",
    "audit",
    "business_identity",
    "cli",
    "contact_map_identity",
    "contacts",
    "dns_policy",
    "evaluator",
    "free_search",
    "frozen_registry",
    "hiring_discovery",
    "inline_recruiting",
    "insights",
    "legal_name_identity",
    "nuu_careers",
    "output_contract",
    "portal_expansion",
    "public_recruiting",
    "publication",
    "readable_report",
    "registry_discovery",
    "report",
    "search",
    "site_discovery",
    "social_ownership",
    "transport_policy",
    "uncovered_recruiting",
    "validate",
    "vilect_careers",
]

# Exact discovered test IDs using README discovery `unittest discover -s tests` (no `tests.` package prefix)
EXPECTED_NODE5_TEST_IDS = [
    "test_report_identity_support.WorkspaceIdentityRendering.test_operator_proof_renders_declaration_without_spans",
    "test_report_identity_support.WorkspaceIdentityRendering.test_contact_map_and_business_proofs_show_all_cited_literal_text",
    "test_report_identity_support.WorkspaceIdentityRendering.test_missing_or_non_array_spans_and_non_object_support_never_throw",
    "test_report_identity_support.WorkspaceIdentityRendering.test_span_and_operator_text_is_escaped",
    "test_report_identity_support.WorkspaceIdentityRendering.test_full_workspace_render_survives_every_proof_shape",
]

EXPECTED_NODE_TEMPLATE_TEST_IDS = [
    "test_report_identity_support.TemplateShape.test_render_uses_guarded_helper_instead_of_direct_span_access",
    "test_report_identity_support.TemplateShape.test_operator_payload_is_still_embedded_as_inert_json",
]

EXPECTED_SCOPED_PRIVACY_MAP_TEST_IDS = [
    "test_scoped_privacy_map_identity.ScopedPrivacyMapIdentity.test_exact_privacy_self_collector_and_literal_host_bind_site",
    "test_scoped_privacy_map_identity.ScopedPrivacyMapIdentity.test_vendor_different_collector_foreign_host_and_conflict_never_bind",
    "test_scoped_privacy_map_identity.ScopedPrivacyMapIdentity.test_contact_map_selects_one_exact_legal_record_not_other_offices",
    "test_scoped_privacy_map_identity.ScopedPrivacyMapIdentity.test_map_requires_declared_host_full_brand_marker_address_and_dom",
    "test_scoped_privacy_map_identity.ScopedPrivacyMapIdentity.test_same_values_in_unrelated_script_are_not_map_proof",
    "test_scoped_privacy_map_identity.ScopedPrivacyMapIdentity.test_record_name_and_address_cannot_be_joined_across_markers",
    "test_scoped_privacy_map_identity.ScopedPrivacyMapIdentity.test_explicit_conflicting_number_inside_marker_overrides_name_and_address",
    "test_scoped_privacy_map_identity.ScopedPrivacyMapIdentity.test_literal_host_boundary_allows_sentence_stop_but_rejects_foreign_suffix_and_email",
    "test_scoped_privacy_map_identity.ScopedPrivacyMapIdentity.test_audit_reconstructs_contact_map_identity_from_retained_chain",
    "test_scoped_privacy_map_identity.ScopedPrivacyMapIdentity.test_audit_rejects_tampered_marker_address_pointer_and_wrong_marker_owner",
    "test_scoped_privacy_map_identity.ScopedPrivacyMapIdentity.test_audit_rejects_missing_contact_page_root_page_or_registry_evidence",
    "test_scoped_privacy_map_identity.ScopedPrivacyMapIdentity.test_audit_rejects_foreign_operator_or_conflicting_org_on_retained_pages",
    "test_scoped_privacy_map_identity.ScopedPrivacyMapIdentity.test_audit_preserves_generic_literal_spans_and_legal_name_branches",
]

EXPECTED_CLI_DOCS_TEST_IDS = [
    "test_cli_docs_consistency.CliDocumentation.test_every_cli_option_is_documented_in_the_option_table",
    "test_cli_docs_consistency.CliDocumentation.test_public_discovery_defaults_match_the_parser",
    "test_cli_docs_consistency.CliDocumentation.test_worker_range_matches_validation",
    "test_cli_docs_consistency.CliDocumentation.test_request_budget_text_matches_summary_constants",
    "test_cli_docs_consistency.CliDocumentation.test_dockerfile_copy_closes_over_all_top_level_and_lazy_local_imports",
    "test_cli_docs_consistency.CliDocumentation.test_copied_modules_do_not_hide_local_imports_behind_import_error_handlers",
    "test_cli_docs_consistency.CliDocumentation.test_dockerignore_allowlist_permits_every_dockerfile_copy_source",
]


class RecordingTestResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.passed_ids: list[str] = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.passed_ids.append(test.id())


def run_package_smoke(product_root: Path, cli_help_file: Path, out_json: Path) -> int:
    sys.path.insert(0, str(product_root))
    py_ver = platform.python_version()
    if py_ver != "3.12.15":
        raise SystemExit(f"Expected Python 3.12.15 in product container, got {py_ver}")

    org_types_file = product_root / "organization_types.json"
    if not org_types_file.is_file():
        raise SystemExit(f"Missing organization_types.json in product image: {org_types_file}")

    help_text = cli_help_file.read_text(encoding="utf-8")
    for required_flag in ("--org-list", "--output", "--summary", "--cache", "--report-dir", "--search"):
        if required_flag not in help_text:
            raise SystemExit(f"CLI --help output missing expected flag {required_flag}")

    imported: list[str] = []
    for mod_name in EXPECTED_ROOT_MODULES:
        mod_file = product_root / f"{mod_name}.py"
        if not mod_file.is_file():
            raise SystemExit(f"Missing root module file in product image: {mod_file}")
        importlib.import_module(mod_name)
        imported.append(mod_name)

    payload = {
        "mode": "package-smoke",
        "passed": True,
        "python_version": py_ver,
        "product_root": str(product_root),
        "organization_types_json_present": True,
        "imported_root_module_count": len(imported),
        "imported_root_modules": imported,
        "cli_help_bytes": len(help_text.encode("utf-8")),
        "cli_help_sha256": hashlib.sha256(help_text.encode("utf-8")).hexdigest(),
        "node_present_in_product_image": shutil.which("node") is not None,
    }
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0


def execute_readme_discovery(product_root: Path) -> tuple[RecordingTestResult, int, float]:
    os.chdir(product_root)
    if str(product_root) not in sys.path:
        sys.path.insert(0, str(product_root))
    test_files = sorted((product_root / "tests").glob("test_*.py"))
    if len(test_files) != 65:
        raise SystemExit(f"Expected 65 test files in tests/test_*.py, found {len(test_files)}")

    started = time.monotonic()
    # Exact README discovery: `python3 -B -m unittest discover -s tests -q` (default top_level_dir=start_dir)
    loader = unittest.defaultTestLoader
    suite = loader.discover(start_dir=str(product_root / "tests"), pattern="test_*.py")
    runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=1, resultclass=RecordingTestResult)
    result: RecordingTestResult = runner.run(suite)  # type: ignore[assignment]
    elapsed_s = round(time.monotonic() - started, 3)
    return result, len(test_files), elapsed_s


def run_core_unit_without_node(product_root: Path, out_json: Path) -> int:
    py_ver = platform.python_version()
    if py_ver != "3.12.15":
        raise SystemExit(f"Expected Python 3.12.15 in core container, got {py_ver}")
    if shutil.which("node") is not None:
        raise SystemExit("Core Python 3.12.15-slim profile should not have node installed")

    result, file_count, elapsed_s = execute_readme_discovery(product_root)
    failed_ids = [test.id() for test, _ in result.failures]
    error_ids = [test.id() for test, _ in result.errors]
    skipped_ids = [test.id() for test, _ in result.skipped]
    passed_set = set(result.passed_ids)

    missing_template2 = [tid for tid in EXPECTED_NODE_TEMPLATE_TEST_IDS if tid not in passed_set]
    missing_scoped13 = [tid for tid in EXPECTED_SCOPED_PRIVACY_MAP_TEST_IDS if tid not in passed_set]
    missing_clidocs7 = [tid for tid in EXPECTED_CLI_DOCS_TEST_IDS if tid not in passed_set]

    # Without Node, the 5 WorkspaceIdentityRendering tests are expected to be skipped and 0 other tests skipped.
    expected_skips_match = sorted(skipped_ids) == sorted(EXPECTED_NODE5_TEST_IDS)
    core_passed = (
        result.wasSuccessful()
        and len(failed_ids) == 0
        and len(error_ids) == 0
        and expected_skips_match
        and len(missing_template2) == 0
        and len(missing_scoped13) == 0
        and len(missing_clidocs7) == 0
    )

    payload = {
        "mode": "core-unit-without-node",
        "profile": "core_python_3_12_15_slim_without_node",
        "passed": core_passed,
        "python_version": py_ver,
        "discovered_test_file_count": file_count,
        "historical_ast_test_method_expectation_not_result": 594,
        "tests_run": result.testsRun,
        "passed_count": len(result.passed_ids),
        "failure_count": len(failed_ids),
        "error_count": len(error_ids),
        "skipped_count": len(skipped_ids),
        "skipped_test_ids": skipped_ids,
        "skipped_are_exclusively_node5_tests": expected_skips_match,
        "template_shape_2_passed": len(missing_template2) == 0,
        "scoped_privacy_map_13_passed": len(missing_scoped13) == 0,
        "cli_docs_consistency_7_passed": len(missing_clidocs7) == 0,
        "elapsed_seconds": elapsed_s,
    }
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0 if core_passed else 1


def run_full_unit_with_node(
    product_root: Path,
    expected_node_version: str,
    node_tarball_sha256: str,
    core_unit_json: Path,
    out_json: Path,
) -> int:
    py_ver = platform.python_version()
    if py_ver != "3.12.15":
        raise SystemExit(f"Expected Python 3.12.15 in validation container, got {py_ver}")

    node_bin = shutil.which("node")
    if not node_bin:
        raise SystemExit("Node binary is required in validation profile for the 5 Node tests, but was not found")

    ldd_proc = subprocess.run(["ldd", node_bin], capture_output=True, text=True, check=True, timeout=15)
    if "not found" in ldd_proc.stdout:
        raise SystemExit(f"Missing dynamic library for node binary:\n{ldd_proc.stdout}")

    node_proc = subprocess.run([node_bin, "--version"], capture_output=True, text=True, check=True, timeout=15)
    actual_node_version = node_proc.stdout.strip()
    if actual_node_version != expected_node_version:
        raise SystemExit(f"Node version mismatch: {actual_node_version} != {expected_node_version}")

    node_sha256 = hashlib.sha256(Path(node_bin).read_bytes()).hexdigest()
    result, file_count, elapsed_s = execute_readme_discovery(product_root)

    failed_ids = [test.id() for test, _ in result.failures]
    error_ids = [test.id() for test, _ in result.errors]
    skipped_ids = [test.id() for test, _ in result.skipped]

    passed_set = set(result.passed_ids)
    missing_node5 = [tid for tid in EXPECTED_NODE5_TEST_IDS if tid not in passed_set]
    missing_template2 = [tid for tid in EXPECTED_NODE_TEMPLATE_TEST_IDS if tid not in passed_set]
    missing_scoped13 = [tid for tid in EXPECTED_SCOPED_PRIVACY_MAP_TEST_IDS if tid not in passed_set]
    missing_clidocs7 = [tid for tid in EXPECTED_CLI_DOCS_TEST_IDS if tid not in passed_set]

    core_summary = json.loads(core_unit_json.read_text(encoding="utf-8"))

    regression_counts = {
        "S-AUDIT-01_scoped_privacy_map_identity_13": len(EXPECTED_SCOPED_PRIVACY_MAP_TEST_IDS) - len(missing_scoped13),
        "S-PACKAGE-01_02_and_DOC1_3_cli_docs_consistency_7": len(EXPECTED_CLI_DOCS_TEST_IDS) - len(missing_clidocs7),
        "5f225f0_template_shape_2": len(EXPECTED_NODE_TEMPLATE_TEST_IDS) - len(missing_template2),
        "5f225f0_node5_workspace_identity_rendering_5": len(EXPECTED_NODE5_TEST_IDS) - len(missing_node5),
    }

    all_passed = (
        bool(core_summary.get("passed"))
        and result.wasSuccessful()
        and len(failed_ids) == 0
        and len(error_ids) == 0
        and len(skipped_ids) == 0
        and len(missing_node5) == 0
        and len(missing_template2) == 0
        and len(missing_scoped13) == 0
        and len(missing_clidocs7) == 0
    )

    summary = {
        "mode": "full-unit-with-node",
        "passed": all_passed,
        "validation_profile": "supplemental_test_only_node_validation_image_with_libstdcpp6_not_browser_e2e",
        "python_version": py_ver,
        "node_binary": node_bin,
        "node_version": actual_node_version,
        "node_binary_sha256": node_sha256,
        "node_official_tarball_sha256": node_tarball_sha256,
        "node_ldd_verified_no_missing_libs": True,
        "discovered_test_file_count": file_count,
        "historical_ast_test_method_expectation_not_result": 594,
        "core_product_container_unit_summary": core_summary,
        "tests_run": result.testsRun,
        "passed_count": len(result.passed_ids),
        "failure_count": len(failed_ids),
        "error_count": len(error_ids),
        "skipped_count": len(skipped_ids),
        "failed_test_ids": failed_ids,
        "error_test_ids": error_ids,
        "skipped_test_ids": skipped_ids,
        "node5_workspace_rendering_test_ids": EXPECTED_NODE5_TEST_IDS,
        "node5_all_executed_and_passed_without_skip": len(missing_node5) == 0 and len(skipped_ids) == 0,
        "node_template_shape_test_ids": EXPECTED_NODE_TEMPLATE_TEST_IDS,
        "targeted_regression_group_pass_counts": regression_counts,
        "elapsed_seconds": elapsed_s,
    }
    out_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0 if all_passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("package-smoke", "core-unit-without-node", "full-unit-with-node"),
        required=True,
    )
    parser.add_argument("--product-root", required=True)
    parser.add_argument("--cli-help-file")
    parser.add_argument("--expected-node-version", default="v24.22.2")
    parser.add_argument("--node-tarball-sha256", default="")
    parser.add_argument("--core-unit-json")
    parser.add_argument("--out-json", required=True)
    args = parser.parse_args()

    product_root = Path(args.product_root).resolve()
    out_json = Path(args.out_json).resolve()
    if args.mode == "package-smoke":
        if not args.cli_help_file:
            raise SystemExit("--cli-help-file is required for --mode package-smoke")
        return run_package_smoke(product_root, Path(args.cli_help_file).resolve(), out_json)
    if args.mode == "core-unit-without-node":
        return run_core_unit_without_node(product_root, out_json)
    if not args.core_unit_json:
        raise SystemExit("--core-unit-json is required for --mode full-unit-with-node")
    return run_full_unit_with_node(
        product_root,
        args.expected_node_version,
        args.node_tarball_sha256,
        Path(args.core_unit_json).resolve(),
        out_json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
