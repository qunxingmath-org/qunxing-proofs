#!/usr/bin/env python3
"""Inspect committed Qunxing proof submissions and pick a deterministic replay queue."""
import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

import yaml
from jsonschema import Draft202012Validator, ValidationError

CI = Path(__file__).resolve().parent
SUBMISSION = re.compile(r"submissions/QX-[PV]-[0-9]{6}/QX-S-[A-Za-z0-9_-]{1,68}")
SHA = re.compile(r"[0-9a-f]{40}")
PART = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
FLAGS = re.compile(r"\b(sorry|admit|axiom|native_decide|implemented_by|extern|unsafe|elab|macro|debug\.[A-Za-z_]+)\b")
FIXED = {"qunxing.yaml", "proof.md", "Challenge.lean", "Solution.lean", "comparator.json",
         "lean-toolchain", "lakefile.toml", "lake-manifest.json", "LICENSE", "formalization.yaml"}
RESULT = "verification.json"
LIMIT = 2 * 1024 * 1024


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.DEVNULL)


def digest(data):
    return sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def require(ok, message):
    if not ok:
        raise ValueError(message)


def list_directories(repo, rev, base):
    if base:
        paths = git(repo, "diff", "--name-only", "--diff-filter=ACMR", "-z", base, rev, "--", "submissions/")
    else:
        paths = git(repo, "ls-tree", "-r", "--name-only", "-z", rev, "--", "submissions/")
    directories = set()
    for path in paths.decode("utf-8").split("\0"):
        if path:
            directory = "/".join(path.split("/")[:3])
            require(SUBMISSION.fullmatch(directory), "Invalid submission directory")
            directories.add(directory)
    return sorted(directories)


def read_submission(repo, rev, directory):
    files = {}
    size = 0
    listing = git(repo, "ls-tree", "-r", "-l", "-z", rev, "--", directory + "/")
    for line in listing.decode("utf-8").split("\0"):
        if not line:
            continue
        attrs, path = line.split("\t", 1)
        mode, kind, oid, length = attrs.split()
        name = path.removeprefix(directory + "/")
        require(mode == "100644" and kind == "blob", "Only regular non-executable files are accepted")
        require(all(PART.fullmatch(part) for part in name.split("/")), "Invalid proof file path")
        size += int(length)
        require(size <= LIMIT, "Submission exceeds 2 MiB")
        require(name in FIXED or name == RESULT or name.endswith(".lean")
                or (name.startswith("records/") and PurePosixPath(name).suffix in (".json", ".sha256")),
                "Unexpected proof file type")
        files[name] = git(repo, "cat-file", "blob", oid)
    return files


def check_records(files, manifest):
    listing = files.get("records/MANIFEST.sha256", b"")
    require(digest(listing) == manifest["records"]["manifest_sha256"], "Record manifest hash mismatch")
    reported = {}
    for line in listing.decode("ascii").splitlines():
        parts = line.split()
        require(len(parts) == 2, "Invalid record manifest line")
        checksum, name = parts
        name = "records/" + name.removeprefix("records/")
        require(name not in reported, "Duplicate record manifest entry")
        reported[name] = checksum
    actual = {name: digest(value) for name, value in files.items()
              if name.startswith("records/") and name != "records/MANIFEST.sha256"}
    require(reported == actual, "Record file hash mismatch")
    run = json.loads(files["records/run.json"])
    Draft202012Validator(read_json(CI / "schemas/run-submission.json")).validate(run)
    require((run["run_ref"], run["problem_id"], run["card_rev"], run["claim_revision"])
            == (manifest["records"]["run_ref"], manifest["problem_id"], manifest["card_rev"], manifest["claim"]["revision"]),
            "Record and submission IDs do not match")
    return run


def inspect(files, directory, lock):
    manifest = yaml.safe_load(files["qunxing.yaml"])
    Draft202012Validator(read_json(CI / "schemas/submission.json")).validate(manifest)
    require(directory.split("/")[1] == manifest["problem_id"], "Submission problem ID does not match its directory")
    require(bool(files.get("proof.md")), "Missing proof text")
    run = check_records(files, manifest)
    proof_hash = digest(json.dumps({name: digest(data) for name, data in files.items() if name != RESULT},
                                  sort_keys=True).encode())
    report = {"schema": "qunxing.verification/1", "submission": directory, "input_sha256": proof_hash}
    if manifest["claim"]["stage"] == "solved_claimed":
        return report | {"status": "INCONCLUSIVE", "reason": "no_lean_project"}
    check_raw = files["records/lean-check.json"]
    check = json.loads(check_raw)
    Draft202012Validator(read_json(CI / "schemas/lean-check.json")).validate(check)
    require(run["lean_check_sha256"] == digest(check_raw), "Wrong Lean check hash")
    challenge = digest(files["Challenge.lean"])
    require(challenge == manifest["statement"]["challenge_sha256"] == check["challenge_sha256"], "Wrong Challenge hash")
    require(digest(files["Solution.lean"]) == check["solution_sha256"], "Wrong Solution hash")
    require(digest(files["lake-manifest.json"]) == check["lake_manifest_sha256"], "Wrong Lake manifest hash")
    require(manifest["toolchain"] == check["toolchain"] == files["lean-toolchain"].decode("ascii").strip(),
            "Toolchain mismatch")
    require("lakefile.toml" in files, "Missing Lake TOML")
    require(manifest["mathlib_rev"] == check["mathlib_rev"], "Mathlib revision mismatch")
    report["source_flags"] = sorted({word for path, data in files.items()
                                     if path.endswith(".lean") and path != "Challenge.lean"
                                     for word in FLAGS.findall(data.decode("utf-8"))})
    entry = lock["challenges"].get(f'{manifest["problem_id"]}@{manifest["card_rev"]}')
    if manifest["statement"]["source"] != "locked" or entry is None:
        return report | {"status": "INCONCLUSIVE", "reason": "canonical_challenge_unavailable"}
    require(challenge == entry["sha256"], "Challenge does not match the protected revision")
    require(manifest["claim"]["theorem_names"] == entry["theorem_names"]
            and manifest["claim"]["definition_names"] == entry["definition_names"],
            "Claim declarations do not match the protected revision")
    profile = lock["profile"]
    if manifest["toolchain"] != profile["toolchain"] or manifest["mathlib_rev"] != profile["mathlib_commit"]:
        return report | {"status": "INCONCLUSIVE", "reason": "unsupported_toolchain"}
    return report | {"status": "READY", "required": manifest["claim"]["kind"] in {"proof", "disproof"}
                     and manifest["problem_id"].startswith("QX-P-")}


def order(queue, limit=30, percent=100):
    ranked = sorted(queue, key=lambda item: (not item["required"], item["commit"], item["submission"]))
    return [item for item in ranked
            if item["required"] or int(digest(item["commit"].encode() + item["submission"].encode())[:8], 16) % 100 < percent][:limit]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    parser.add_argument("rev")
    parser.add_argument("--base")
    parser.add_argument("--queue", action="store_true")
    args = parser.parse_args()
    require(SHA.fullmatch(args.rev) and (args.base is None or SHA.fullmatch(args.base)), "Expected immutable Git SHAs")
    lock = read_json(CI / "locks.json")
    queue = []
    failed = False
    for path in list_directories(args.repo, args.rev, args.base):
        try:
            files = read_submission(args.repo, args.rev, path)
            verdict = inspect(files, path, lock)
        except (KeyError, ValueError, ValidationError, yaml.YAMLError):
            print(f"{path}: invalid proof boundary", file=sys.stderr)
            failed = True
            continue
        if not args.queue:
            print(json.dumps(verdict))
            continue
        if verdict["status"] != "READY":
            print(f"{path}: {verdict['reason']}", file=sys.stderr)
            continue
        if RESULT in files:
            previous = json.loads(files[RESULT])
            if previous.get("input_sha256") == verdict["input_sha256"] and previous.get("status") in {"PASS", "FAIL"}:
                continue
        first_parent = git(args.repo, "log", "-1", "--first-parent", "--format=%H", args.rev, "--", path + "/qunxing.yaml")
        queue.append({"submission": path, "required": verdict["required"], "commit": first_parent.decode().strip()})
    if args.queue:
        print(json.dumps({"include": order(queue, percent=lock["sample_percent"])}))
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
