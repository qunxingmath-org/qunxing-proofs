"""Reproducible boundary and queue checks with synthetic proofs."""
from copy import deepcopy
import json
import unittest

import yaml

from gate import CI, digest, inspect, order, read_json

SUBMISSION = "submissions/QX-P-000005/QX-S-fixture"
SAMPLE_MANIFEST = "schema: qunxing.submission/1\nconsent_version: 2026-11-v5\nproblem_id: QX-P-000005\ncard_rev: \"5a3593e08bf63a81\"\nstatement:\n  source: self            # locked：题卡锁定的 Challenge；self：本次自己写的（星星带\"题面未锁定\"）\n  challenge_sha256: \"df286072e0cc32ff579b0e9a7434c066dc56576017b3c465fb569a7c7c39be7f\"\n  review:                 # 题意复核；没做写 null\n    vendor: anthropic\n    model: example-review-model\n    verdict: PASS\n    verdict_sha256: \"da133ff6f3999bd5db0680c221b8dbad732874d0e9b9fa42b1cec8769434e641\"\nclaim:\n  kind: proof\n  stage: statement_ok     # solved_claimed / formal_local / statement_ok\n  revision: 2\n  theorem_names: [Qunxing.P000005.main]\n  definition_names: []\ntoolchain: leanprover/lean4:v4.25.0\nmathlib_rev: \"e307009ca9fac58c88d965a460600ff51348e8ca\"\nrecords:\n  manifest_sha256: \"c973113d54c00f1fe475cbea01b159757ddc0b9880852eb11f3c32d43703c3b2\"\n  run_ref: \"3908d45292a7734a\"\ndisclosure:\n  vendors: [openai, anthropic, deepseek]\n  models: [example-solver-model, example-review-model, example-search-model]\n  harness: [codex, claude-code, other]\nlicense:\n  code: Apache-2.0\n  text: CC-BY-SA-4.0\ndestinations:\n  dataset: true           # 群星公开数据集（qunxing-proofs）\n  own_repo: null          # 或 {repo: 用户名/仓库名, path: qunxing/QX-P-000005}\n"
SAMPLE_RUN = json.loads("{\"schema\":\"qunxing.run-submission/1\",\"run_ref\":\"3908d45292a7734a\",\"problem_id\":\"QX-P-000005\",\"card_rev\":\"5a3593e08bf63a81\",\"claim_revision\":2,\"sessions\":[{\"stage\":\"novelty_pre\",\"ledger\":\"novelty\",\"kind\":\"fresh\",\"vendor\":\"deepseek\",\"harness\":\"other\",\"cli_version\":\"1.0\",\"model\":\"example-search-model\",\"fresh_context\":true},{\"stage\":\"solve\",\"ledger\":\"solve\",\"kind\":\"main\",\"vendor\":\"openai\",\"harness\":\"codex\",\"cli_version\":\"0.63.0\",\"model\":\"example-solver-model\",\"fresh_context\":true},{\"stage\":\"formal\",\"ledger\":\"verify\",\"kind\":\"fresh\",\"vendor\":\"openai\",\"harness\":\"codex\",\"cli_version\":\"0.63.0\",\"model\":\"example-solver-model\",\"fresh_context\":true},{\"stage\":\"audit_claim\",\"ledger\":\"verify\",\"kind\":\"fresh\",\"vendor\":\"anthropic\",\"harness\":\"claude-code\",\"cli_version\":\"2.1.3\",\"model\":\"example-review-model\",\"fresh_context\":true}],\"novelty_post\":null,\"lean_check_sha256\":\"6405fe220a06eabd45b89e0e7ef67c4739d339647ce6d7790d3c277bcd0d0314\",\"verdicts_sha256\":[\"da133ff6f3999bd5db0680c221b8dbad732874d0e9b9fa42b1cec8769434e641\"]}")
SAMPLE_CHECK = json.loads("{\"schema\":\"qunxing.lean-check/1\",\"challenge_sha256\":\"df286072e0cc32ff579b0e9a7434c066dc56576017b3c465fb569a7c7c39be7f\",\"solution_sha256\":\"1282b3a9d7342bdd56548e2e16ed2e6d3b17f26c9d13df2e1b9beffb59570a8a\",\"toolchain\":\"leanprover/lean4:v4.25.0\",\"mathlib_rev\":\"e307009ca9fac58c88d965a460600ff51348e8ca\",\"lake_manifest_sha256\":\"975a1ede6b811b4e7596fae6cef3da026732bf07178a7590b82f1e95d64273a2\",\"commands\":[{\"cmd\":\"lake exe cache get\",\"exit_code\":0},{\"cmd\":\"lake build\",\"exit_code\":0},{\"cmd\":\"lake env lean Solution.lean\",\"exit_code\":0},{\"cmd\":\"lake exe comparator comparator.json\",\"exit_code\":0},{\"cmd\":\"lake env leanchecker --fresh Solution\",\"exit_code\":0}],\"axioms\":[\"propext\",\"Classical.choice\",\"Quot.sound\"],\"comparator\":{\"version\":\"0.3.1\",\"result\":\"pass\"},\"leanchecker\":{\"version\":\"4.25.0\",\"result\":\"pass\"}}")



def fixture():
    manifest = yaml.safe_load(SAMPLE_MANIFEST)
    manifest["statement"]["source"] = "locked"
    files = {
        "proof.md": b"A test fixture.\n",
        "Challenge.lean": b"theorem sampleAdd : 1 + 1 = 2 := by sorry\n",
        "Solution.lean": b"theorem sampleAdd : 1 + 1 = 2 := rfl\n",
        "lakefile.toml": b'name = "test"\n',
        "lake-manifest.json": b'{"packages":[]}\n',
        "lean-toolchain": manifest["toolchain"].encode(),
    }
    run, check = deepcopy(SAMPLE_RUN), deepcopy(SAMPLE_CHECK)
    check.update(challenge_sha256=digest(files["Challenge.lean"]),
                 solution_sha256=digest(files["Solution.lean"]),
                 lake_manifest_sha256=digest(files["lake-manifest.json"]))
    raw_check = json.dumps(check).encode()
    run["lean_check_sha256"] = digest(raw_check)
    files["records/lean-check.json"] = raw_check
    files["records/run.json"] = json.dumps(run).encode()
    listing = "".join(f"{digest(value)}  {name}\n" for name, value in files.items() if name.startswith("records/"))
    files["records/MANIFEST.sha256"] = listing.encode()
    manifest["records"]["manifest_sha256"] = digest(listing.encode())
    manifest["statement"]["challenge_sha256"] = check["challenge_sha256"]
    files["qunxing.yaml"] = json.dumps(manifest).encode()
    lock = read_json(CI / "locks.json")
    profile = lock["profile"]
    profile.update(toolchain=manifest["toolchain"], mathlib_commit=manifest["mathlib_rev"])
    lock["challenges"] = {f'{manifest["problem_id"]}@{manifest["card_rev"]}': {
        "sha256": check["challenge_sha256"],
        "theorem_names": manifest["claim"]["theorem_names"],
        "definition_names": manifest["claim"]["definition_names"],
    }}
    return files, lock


class GateTests(unittest.TestCase):
    def test_locked_candidate_is_ready_for_replay(self):
        files, lock = fixture()
        self.assertTrue(inspect(files, SUBMISSION, lock)["required"])
        self.assertEqual(inspect(files, SUBMISSION, lock)["status"], "READY")

    def test_missing_canonical_challenge_is_inconclusive(self):
        files, lock = fixture()
        lock["challenges"] = {}
        self.assertEqual(inspect(files, SUBMISSION, lock)["reason"], "canonical_challenge_unavailable")

    def test_wrong_digest_and_record_mismatch_rejected(self):
        files, lock = fixture()
        files["Solution.lean"] += b"\n"
        with self.assertRaisesRegex(ValueError, "Wrong Solution hash"):
            inspect(files, SUBMISSION, lock)
        files, lock = fixture()
        files["records/run.json"] += b"\n"
        with self.assertRaisesRegex(ValueError, "Record file hash"):
            inspect(files, SUBMISSION, lock)

    def test_ineligible_releases_never_mark_a_proof_as_replayed(self):
        files, lock = fixture()
        lock["profile"]["toolchain"] = "leanprover/lean4:v0.0.0"
        self.assertEqual(inspect(files, SUBMISSION, lock)["reason"], "unsupported_toolchain")

    def test_daily_limit_and_required_priority(self):
        candidates = [{"commit": f"{index:040x}", "submission": str(index), "required": index % 2 == 0}
                      for index in range(61)]
        self.assertEqual(len(order(candidates)), 30)
        self.assertTrue(all(row["required"] for row in order(candidates, percent=0)))
        self.assertEqual(order(candidates), order(reversed(candidates)))


if __name__ == "__main__":
    unittest.main()
