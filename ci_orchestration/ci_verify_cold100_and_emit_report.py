#!/usr/bin/env python3
"""Validate Signalpost Cold-100 output envelopes using exact product DTO, run audit.py, and emit report (CI-V1-04)."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def percentile_nearest_rank(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil((pct / 100.0) * len(ordered)))
    return round(float(ordered[rank - 1]), 2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product-root", required=True)
    parser.add_argument("--novas100", required=True)
    parser.add_argument("--amostra100", required=True)
    parser.add_argument("--step1-json", required=True)
    parser.add_argument("--step2-json", required=True)
    parser.add_argument("--step3-json", required=True)
    parser.add_argument("--step4-json", required=True)
    parser.add_argument("--result-jsonl", required=True)
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--review-dir", required=True)
    parser.add_argument("--product-image-id", required=True)
    parser.add_argument("--validation-image-id", required=True)
    parser.add_argument("--out-report-json", required=True)
    parser.add_argument("--out-report-md", required=True)
    args = parser.parse_args()

    product_root = Path(args.product_root).resolve()
    sys.path.insert(0, str(product_root))

    import audit as audit_mod
    import output_contract as contract_mod
    import validate as validate_mod

    step1 = json.loads(Path(args.step1_json).read_text(encoding="utf-8"))
    step2 = json.loads(Path(args.step2_json).read_text(encoding="utf-8"))
    step3 = json.loads(Path(args.step3_json).read_text(encoding="utf-8"))
    step4 = json.loads(Path(args.step4_json).read_text(encoding="utf-8"))

    if not step4.get("container_closure_verified"):
        raise SystemExit("Step 4 Cold-100 container closure was not verified before auditing outputs")

    novas_path = Path(args.novas100).resolve()
    amostra_path = Path(args.amostra100).resolve()
    expected_orgs = [line.strip() for line in novas_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    amostra = json.loads(amostra_path.read_text(encoding="utf-8"))

    result_path = Path(args.result_jsonl).resolve()
    summary_path = Path(args.summary_json).resolve()
    cache_dir = Path(args.cache_dir).resolve()
    review_dir = Path(args.review_dir).resolve()

    rows = load_jsonl(result_path)
    output_sha256 = sha256_file(result_path) if result_path.is_file() else None
    summary_sha256 = sha256_file(summary_path) if summary_path.is_file() else None
    cli_summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else None

    val_result = validate_mod.validate(rows, expected_orgs)
    audit_result = audit_mod.audit(rows, str(cache_dir))

    per_org_records: list[dict] = []
    terminal_status_counts: Counter[str] = Counter()
    cli_outcome_counts: Counter[str] = Counter()
    claim_availability_totals: Counter[str] = Counter()
    primary_claim_availability_totals: Counter[str] = Counter()
    policy_breaches: list[str] = []

    request_values: list[int] = []
    runtime_ms_values: list[float] = []
    cost_values: list[float] = []
    orgs_with_available_claims = 0
    orgs_with_verified_website = 0

    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            policy_breaches.append(f"row[{idx}] is not a dict")
            continue

        # Exact DTO: row['organisation_number'] string
        org_raw = row.get("organisation_number")
        if not isinstance(org_raw, str) or not org_raw.strip():
            policy_breaches.append(f"row[{idx}] missing or non-string organisation_number")
            org_id = ""
        else:
            org_id = org_raw

        row_contract_errors = contract_mod.contract_errors(row)
        if row_contract_errors:
            policy_breaches.append(f"row[{idx}] org={org_id} contract_errors={row_contract_errors}")

        run_obj = row.get("run")
        if not isinstance(run_obj, dict) or run_obj.get("terminal_status") not in ("completed", "failed"):
            policy_breaches.append(f"row[{idx}] org={org_id} invalid run.terminal_status")
            term_status = "invalid"
        else:
            term_status = str(run_obj["terminal_status"])
        terminal_status_counts[term_status] += 1

        cli_obj = row.get("_cli")
        cli_outcome = str(cli_obj.get("outcome")) if isinstance(cli_obj, dict) and isinstance(cli_obj.get("outcome"), str) else "missing"
        cli_outcome_counts[cli_outcome] += 1

        # Exact DTO: row['operations'] has requests, third_party_cost_usd, runtime_ms; never coalesce missing to 0
        ops_obj = row.get("operations")
        reqs_val: int | None = None
        cost_val: float | None = None
        runtime_val: float | None = None
        if not isinstance(ops_obj, dict):
            policy_breaches.append(f"row[{idx}] org={org_id} missing operations dict")
        else:
            raw_reqs = ops_obj.get("requests")
            if type(raw_reqs) is not int or raw_reqs < 0:
                policy_breaches.append(f"row[{idx}] org={org_id} missing or invalid operations.requests={raw_reqs!r}")
            else:
                reqs_val = raw_reqs
                request_values.append(reqs_val)
                if reqs_val > 24:
                    policy_breaches.append(f"row[{idx}] org={org_id} operations.requests={reqs_val} exceeds cap 24")

            raw_cost = ops_obj.get("third_party_cost_usd")
            if type(raw_cost) not in (int, float) or not math.isfinite(float(raw_cost)):
                policy_breaches.append(f"row[{idx}] org={org_id} missing or invalid operations.third_party_cost_usd={raw_cost!r}")
            else:
                cost_val = float(raw_cost)
                cost_values.append(cost_val)
                if cost_val != 0.0:
                    policy_breaches.append(f"row[{idx}] org={org_id} operations.third_party_cost_usd={cost_val} != 0")

            raw_runtime = ops_obj.get("runtime_ms")
            if type(raw_runtime) not in (int, float) or not math.isfinite(float(raw_runtime)) or float(raw_runtime) < 0:
                policy_breaches.append(f"row[{idx}] org={org_id} missing or invalid operations.runtime_ms={raw_runtime!r}")
            else:
                runtime_val = float(raw_runtime)
                runtime_ms_values.append(runtime_val)

        # Exact DTO: row['claims'] is a LIST of dicts {field, availability, value, evidence_ids, ...}
        claims_list = row.get("claims")
        row_claim_counts: Counter[str] = Counter()
        row_primary_claim_counts: Counter[str] = Counter()
        website_status = "none_on_failed_row" if term_status == "failed" else "missing"
        website_url: str | None = None

        if not isinstance(claims_list, list):
            policy_breaches.append(f"row[{idx}] org={org_id} claims is not a list")
        else:
            for claim in claims_list:
                if not isinstance(claim, dict):
                    policy_breaches.append(f"row[{idx}] org={org_id} non-dict claim entry")
                    continue
                field_name = claim.get("field")
                avail = claim.get("availability")
                if not isinstance(field_name, str) or not isinstance(avail, str):
                    policy_breaches.append(f"row[{idx}] org={org_id} claim missing string field/availability")
                    continue
                row_claim_counts[avail] += 1
                claim_availability_totals[avail] += 1
                if not claim.get("alias_of"):
                    row_primary_claim_counts[avail] += 1
                    primary_claim_availability_totals[avail] += 1
                if field_name == "website.verified_url":
                    website_status = avail
                    if avail == "available" and isinstance(claim.get("value"), str):
                        website_url = claim["value"]

        avail_count = int(row_primary_claim_counts.get("available", 0))
        if avail_count > 0:
            orgs_with_available_claims += 1
        if website_status == "available":
            orgs_with_verified_website += 1

        per_org_records.append(
            {
                "index": idx + 1,
                "organisation_number": org_id,
                "terminal_status": term_status,
                "cli_outcome": cli_outcome,
                "requests": reqs_val,
                "runtime_ms": runtime_val,
                "third_party_cost_usd": cost_val,
                "primary_available_claims": avail_count,
                "primary_not_available_claims": int(row_primary_claim_counts.get("not_available", 0)),
                "primary_blocked_claims": int(row_primary_claim_counts.get("blocked", 0)),
                "primary_failed_claims": int(row_primary_claim_counts.get("failed", 0)),
                "website_verified_url_availability": website_status,
                "website_verified_url": website_url,
            }
        )

    cli_exit_code = int(step4.get("cli_exit_code", -1))
    cli_exit_code_acceptable = cli_exit_code in (0, 2) and bool(step4.get("exit_code_acceptable"))
    completed_100_envelopes = (
        len(rows) == 100
        and [r["organisation_number"] for r in per_org_records] == expected_orgs
        and len(request_values) == 100
        and len(runtime_ms_values) == 100
        and len(cost_values) == 100
    )
    review_index_exists = (review_dir / "index.html").is_file()

    # Verify CLI summary actual top-level fields (no nonexistent 'metrics' key)
    cli_summary_subset = None
    if isinstance(cli_summary, dict):
        cli_summary_subset = {
            "schema": cli_summary.get("schema"),
            "format": cli_summary.get("format"),
            "mode": cli_summary.get("mode"),
            "search": cli_summary.get("search"),
            "inputs": cli_summary.get("inputs"),
            "outputs": cli_summary.get("outputs"),
            "unique_valid_companies": cli_summary.get("unique_valid_companies"),
            "unsuccessful_entries": cli_summary.get("unsuccessful_entries"),
            "run_terminal_status_counts": cli_summary.get("run_terminal_status_counts"),
            "claim_status_counts": cli_summary.get("claim_status_counts"),
            "requests": cli_summary.get("requests"),
            "robots_policy_reuse_hits": cli_summary.get("robots_policy_reuse_hits"),
            "request_budget_per_unique_company": cli_summary.get("request_budget_per_unique_company"),
            "request_budget_total": cli_summary.get("request_budget_total"),
            "third_party_cost_usd": cli_summary.get("third_party_cost_usd"),
            "rejected_collector_envelopes": cli_summary.get("rejected_collector_envelopes"),
            "output_sha256": cli_summary.get("output_sha256"),
            "official_score": cli_summary.get("official_score"),
            "review": cli_summary.get("review"),
            "note": cli_summary.get("note"),
        }
        if cli_summary.get("output_sha256") != output_sha256:
            policy_breaches.append("CLI summary output_sha256 does not match result.jsonl SHA256")
        if cli_summary.get("third_party_cost_usd") != 0:
            policy_breaches.append(f"CLI summary third_party_cost_usd={cli_summary.get('third_party_cost_usd')} != 0")

    cold100_passed = (
        completed_100_envelopes
        and cli_exit_code_acceptable
        and bool(val_result.get("structurally_valid"))
        and bool(audit_result.get("passed"))
        and len(policy_breaches) == 0
        and summary_sha256 is not None
        and review_index_exists
    )

    overall_status = (
        "QUALIFIED_100_SMOKE_AND_UNIT_NODE5_PASS"
        if (step1.get("verified") and step2.get("passed") and step3.get("passed") and cold100_passed)
        else "PARTIAL_OR_FAILED_SEE_DIAGNOSTICS"
    )

    total_requests = sum(request_values) if len(request_values) == 100 else None
    mean_requests = round(total_requests / 100.0, 2) if total_requests is not None else None
    max_requests = max(request_values) if request_values else None
    total_cost_usd = sum(cost_values) if len(cost_values) == 100 else None

    runtime_stats = {
        "count_with_valid_runtime_ms": len(runtime_ms_values),
        "min_runtime_ms": round(min(runtime_ms_values), 2) if runtime_ms_values else None,
        "p50_runtime_ms": percentile_nearest_rank(runtime_ms_values, 50.0),
        "p95_runtime_ms": percentile_nearest_rank(runtime_ms_values, 95.0),
        "max_runtime_ms": round(max(runtime_ms_values), 2) if runtime_ms_values else None,
        "mean_runtime_ms": round(sum(runtime_ms_values) / len(runtime_ms_values), 2) if runtime_ms_values else None,
    }

    audit_counts = audit_result.get("counts") if isinstance(audit_result.get("counts"), dict) else {}

    report_payload = {
        "schema": "signalpost.ci.qualification_report.v2",
        "overall_status": overall_status,
        "product_under_test": {
            "product_commit_sha1": step1["product_commit_sha1"],
            "product_tree_sha1": step1["product_tree_sha1"],
            "verified_product_file_count": step1["verified_product_file_count"],
            "manifest_945_sha256": step1["manifest_945_sha256"],
            "workflow_commit_sha1": step1["workflow_commit_sha1"],
            "workflow_commit_distinct_from_product_commit": step1["workflow_commit_distinct_from_product_commit"],
            "product_docker_image_id": args.product_image_id,
            "validation_docker_image_id": args.validation_image_id,
            "python_base_image": "python:3.12.15-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704",
        },
        "package_and_cli_smoke": step2,
        "unit_and_node5_validation": step3,
        "cold100_diagnostic_sample": {
            "sample_nature": "prespecified_diagnostic_100_sample_not_official_shared_scoring_batch",
            "official_score": None,
            "precision": None,
            "recall": None,
            "input_file": "NOVAS100-20261109.txt",
            "input_bytes": step1["novas100_bytes"],
            "input_sha256": step1["novas100_sha256"],
            "metadata_file": "AMOSTRA-NOVA100-PREDEFINIDA-20261109.json",
            "metadata_bytes": step1["amostra100_bytes"],
            "metadata_sha256": step1["amostra100_sha256"],
            "known_sample_composition": amostra.get("counts", {}),
            "sample_limitations_note": (
                "Prespecified diagnostic sample of 100 Norwegian companies (90 AS / 10 ASA; "
                "44 with Brreg website hint / 56 without hint). Not an official shared scoring batch; "
                "ordinary blocked/not_available claims are legitimate collector states."
            ),
            "container_execution_and_closure": step4,
            "completed_100_envelopes": completed_100_envelopes,
            "envelopes_emitted": len(rows),
            "output_jsonl_sha256": output_sha256,
            "summary_json_sha256": summary_sha256,
            "review_index_html_generated": review_index_exists,
            "validate_structurally_valid": bool(val_result.get("structurally_valid")),
            "validate_error_count": len(val_result.get("errors") or []),
            "validate_errors": (val_result.get("errors") or [])[:20],
            "validate_note": val_result.get("note"),
            "audit_passed": bool(audit_result.get("passed")),
            "audit_counts": dict(sorted(audit_counts.items())),
            "audit_external_identity_review_count": len(audit_result.get("external_identity_review") or []),
            "audit_error_count": len(audit_result.get("errors") or []),
            "audit_errors": (audit_result.get("errors") or [])[:20],
            "audit_limitations": audit_result.get("limitations"),
            "policy_breaches": policy_breaches[:20],
            "terminal_status_counts": dict(sorted(terminal_status_counts.items())),
            "cli_outcome_counts": dict(sorted(cli_outcome_counts.items())),
            "claim_availability_totals_including_official_website_alias": dict(sorted(claim_availability_totals.items())),
            "primary_claim_availability_totals": dict(sorted(primary_claim_availability_totals.items())),
            "orgs_with_available_claims": orgs_with_available_claims,
            "orgs_with_verified_website": orgs_with_verified_website,
            "total_requests": total_requests,
            "mean_requests_per_org": mean_requests,
            "max_requests_per_org": max_requests,
            "runtime_ms_summary": runtime_stats,
            "total_third_party_cost_usd": total_cost_usd,
            "cli_summary_fields": cli_summary_subset,
            "per_org_outcomes": per_org_records,
        },
    }

    Path(args.out_report_json).write_text(
        json.dumps(report_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    core_unit = step3.get("core_product_container_unit_summary") or {}
    md_lines = [
        "# Signalpost Qualification Report (`1a50b433f98dcb3bf89e5f7b8356ba4729c905ab`)",
        "",
        f"- **Overall Status:** `{overall_status}`",
        f"- **Product Commit SHA-1:** `{step1['product_commit_sha1']}`",
        f"- **Product Tree SHA-1:** `{step1['product_tree_sha1']}` (`{step1['verified_product_file_count']}` files verified against `TARGET-1a50b43-MANIFEST-945.json`)",
        f"- **Workflow Commit SHA-1 (separate orchestration commit):** `{step1['workflow_commit_sha1']}`",
        f"- **Product Base Image:** `{report_payload['product_under_test']['python_base_image']}`",
        "",
        "## 1. Unit Suite: Core Python `3.12.15-slim` vs Supplemental `Node5` Validation Profile",
        f"- **Core Product Container (`without node`):** `testsRun={core_unit.get('tests_run')}`, `passed={core_unit.get('passed_count')}`, `skipped={core_unit.get('skipped_count')}` (exclusively the 5 `WorkspaceIdentityRendering` Node tests: `{core_unit.get('skipped_are_exclusively_node5_tests')}`), `failures={core_unit.get('failure_count')}`, `errors={core_unit.get('error_count')}`",
        f"- **Supplemental Validation Image (`with libstdc++6 + Node {step3['node_version']}`):** `testsRun={step3['tests_run']}`, `passed={step3['passed_count']}`, `skipped={step3['skipped_count']}`, `failures={step3['failure_count']}`, `errors={step3['error_count']}`",
        f"- **All 5 `WorkspaceIdentityRendering` Node Tests Executed & Passed (0 Skips):** `{step3['node5_all_executed_and_passed_without_skip']}`",
        f"- **Targeted Regression Group Pass Counts:** `{json.dumps(step3['targeted_regression_group_pass_counts'], sort_keys=True)}`",
        "",
        "## 2. Cold-100 Diagnostic Batch (`--search none`, Empty Cache, USD 0)",
        f"- **Sample & Audit Limitations:** {report_payload['cold100_diagnostic_sample']['sample_limitations_note']} `audit.py`: {audit_result.get('limitations')}",
        f"- **Input `NOVAS100-20261109.txt` SHA-256:** `{step1['novas100_sha256']}`",
        f"- **Output `result.jsonl` SHA-256:** `{output_sha256}`",
        f"- **Summary `result.summary.json` SHA-256:** `{summary_sha256}`",
        f"- **Container Closure Verified Before Audit:** `{step4.get('container_closure_verified')}` (`cli_exit_code={cli_exit_code}`, `wall_clock_seconds={step4.get('wall_clock_seconds')}`)",
        f"- **Envelopes Emitted:** `{len(rows)} / 100` (`completed_100_envelopes={completed_100_envelopes}`)",
        f"- **Structural Validation (`validate.py`):** `structurally_valid={val_result.get('structurally_valid')}` (`errors={len(val_result.get('errors') or [])}`)",
        f"- **Source Evidence Audit (`audit.py`):** `passed={audit_result.get('passed')}` (`counts={json.dumps(dict(sorted(audit_counts.items())))}`, `errors={len(audit_result.get('errors') or [])}`)",
        f"- **Terminal Status Counts (`run.terminal_status`):** `{json.dumps(dict(sorted(terminal_status_counts.items())))}`",
        f"- **CLI Outcome Counts (`_cli.outcome`):** `{json.dumps(dict(sorted(cli_outcome_counts.items())))}`",
        f"- **Primary Claim Availability Counts:** `{json.dumps(dict(sorted(primary_claim_availability_totals.items())))}` (`orgs_with_available_claims={orgs_with_available_claims}`, `orgs_with_verified_website={orgs_with_verified_website}`)",
        f"- **Operations Metrics:** `total_requests={total_requests}`, `mean_requests={mean_requests}`, `max_requests={max_requests}` (cap `<= 24`), `third_party_cost_usd={total_cost_usd}`, `runtime_ms={json.dumps(runtime_stats, sort_keys=True)}`",
        "",
        "## 3. Per-Organization Terminal Statuses (100 Orgs)",
        "| # | Organisation Number | Terminal Status | CLI Outcome | Website Availability | Primary Available Claims | Requests | Runtime (ms) |",
        "|---:|:---|:---|:---|:---|---:|---:|---:|",
    ]
    for rec in per_org_records:
        md_lines.append(
            f"| {rec['index']} | `{rec['organisation_number']}` | `{rec['terminal_status']}` | `{rec['cli_outcome']}` | `{rec['website_verified_url_availability']}` | {rec['primary_available_claims']} | {rec['requests']} | {rec['runtime_ms']} |"
        )

    Path(args.out_report_md).write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    if overall_status != "QUALIFIED_100_SMOKE_AND_UNIT_NODE5_PASS":
        print(f"Qualification gate did not pass completely: {overall_status}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
