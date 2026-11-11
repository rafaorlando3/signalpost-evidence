#!/usr/bin/env python3
"""Verify clean materialization of immutable Signalpost product tree 1a50b43 (945 files) and input pins (CI-V1-01)."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

EXPECTED_NOVAS100_SHA256 = "4a348a856c5f23c199e6ddb650c327a5e2cb6b292f4fe331423069919bc4f19c"
EXPECTED_AMOSTRA100_SHA256 = "98756f5c07b42f737a0e1cda92d95727c5b74d438864c1e4e93a55d16935da6b"
EXPECTED_MANIFEST945_SHA256 = "97371e3450c9140cd9533d9141f1e4b864027784fd6d4006f8088c52e73eff8a"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def verify_manifest_dict_against_dir(manifest: dict, product_dir: Path, expected_commit: str, expected_tree: str) -> int:
    if manifest.get("commit_sha1") != expected_commit:
        raise SystemExit(f"Manifest commit_sha1 mismatch: {manifest.get('commit_sha1')} != {expected_commit}")
    if manifest.get("tree_sha1") != expected_tree:
        raise SystemExit(f"Manifest tree_sha1 mismatch: {manifest.get('tree_sha1')} != {expected_tree}")
    if manifest.get("file_count") != 945:
        raise SystemExit(f"Manifest file_count mismatch: {manifest.get('file_count')} != 945")

    expected_files = manifest.get("files")
    if not isinstance(expected_files, dict) or len(expected_files) != 945:
        raise SystemExit("Manifest files must be a dict of 945 path entries")

    actual_files = sorted(
        p.relative_to(product_dir).as_posix()
        for p in product_dir.rglob("*")
        if p.is_file() or p.is_symlink()
    )
    expected_paths = sorted(expected_files.keys())
    if actual_files != expected_paths:
        extra = sorted(set(actual_files) - set(expected_paths))[:10]
        missing = sorted(set(expected_paths) - set(actual_files))[:10]
        raise SystemExit(f"Product tree file list mismatch: extra={extra} missing={missing}")

    for rel_path, entry in expected_files.items():
        if not isinstance(entry, dict):
            raise SystemExit(f"Invalid manifest entry for {rel_path}")
        file_path = product_dir / rel_path
        if file_path.is_symlink():
            raise SystemExit(f"Unexpected symlink in product tree: {rel_path}")
        mode = entry.get("mode")
        if mode not in ("100644", "100755"):
            raise SystemExit(f"Unexpected git mode {mode} for {rel_path}")
        is_exec = bool(file_path.stat().st_mode & 0o111)
        if is_exec != (mode == "100755"):
            raise SystemExit(f"Executable mode mismatch for {rel_path}: mode={mode} is_exec={is_exec}")
        raw = file_path.read_bytes()
        if len(raw) != entry.get("bytes"):
            raise SystemExit(f"Byte length mismatch for {rel_path}: {len(raw)} != {entry.get('bytes')}")
        if git_blob_sha1(raw) != entry.get("git_blob_sha1"):
            raise SystemExit(f"Git blob SHA1 mismatch for {rel_path}")
        if sha256_bytes(raw) != entry.get("sha256"):
            raise SystemExit(f"SHA256 mismatch for {rel_path}")

    return len(expected_files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product-dir", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--novas100", required=True)
    parser.add_argument("--amostra100", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-tree", required=True)
    parser.add_argument("--workflow-commit", required=True)
    parser.add_argument("--out-json", required=True)
    args = parser.parse_args()

    product_dir = Path(args.product_dir).resolve()
    manifest_path = Path(args.manifest).resolve()
    novas_path = Path(args.novas100).resolve()
    amostra_path = Path(args.amostra100).resolve()

    manifest_raw = manifest_path.read_bytes()
    manifest_sha256 = sha256_bytes(manifest_raw)
    if manifest_sha256 != EXPECTED_MANIFEST945_SHA256:
        raise SystemExit(
            f"TARGET-1a50b43-MANIFEST-945.json SHA256 mismatch: {manifest_sha256} != {EXPECTED_MANIFEST945_SHA256}"
        )

    manifest = json.loads(manifest_raw.decode("utf-8"))
    verified_count = verify_manifest_dict_against_dir(
        manifest, product_dir, args.expected_commit, args.expected_tree
    )

    novas_raw = novas_path.read_bytes()
    novas_sha256 = sha256_bytes(novas_raw)
    if novas_sha256 != EXPECTED_NOVAS100_SHA256:
        raise SystemExit(f"NOVAS100 SHA256 mismatch: {novas_sha256} != {EXPECTED_NOVAS100_SHA256}")

    amostra_raw = amostra_path.read_bytes()
    amostra_sha256 = sha256_bytes(amostra_raw)
    if amostra_sha256 != EXPECTED_AMOSTRA100_SHA256:
        raise SystemExit(f"AMOSTRA100 SHA256 mismatch: {amostra_sha256} != {EXPECTED_AMOSTRA100_SHA256}")

    org_lines = [line.strip() for line in novas_raw.decode("utf-8").splitlines() if line.strip()]
    if len(org_lines) != 100 or len(set(org_lines)) != 100:
        raise SystemExit(f"Expected 100 unique org IDs in NOVAS100, got len={len(org_lines)} unique={len(set(org_lines))}")

    amostra = json.loads(amostra_raw.decode("utf-8"))
    amostra_orgs = [str(item["org"]) for item in amostra.get("companies", [])]
    if org_lines != amostra_orgs:
        raise SystemExit("NOVAS100 org order does not match AMOSTRA-NOVA100-PREDEFINIDA-20261109.json companies order")

    summary = {
        "verified": True,
        "product_commit_sha1": args.expected_commit,
        "product_tree_sha1": args.expected_tree,
        "workflow_commit_sha1": args.workflow_commit,
        "workflow_commit_distinct_from_product_commit": args.workflow_commit != args.expected_commit,
        "verified_product_file_count": verified_count,
        "manifest_945_sha256": manifest_sha256,
        "novas100_sha256": novas_sha256,
        "novas100_bytes": len(novas_raw),
        "novas100_unique_org_count": len(org_lines),
        "amostra100_sha256": amostra_sha256,
        "amostra100_bytes": len(amostra_raw),
    }
    Path(args.out_json).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
