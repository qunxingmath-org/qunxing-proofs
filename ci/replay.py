#!/usr/bin/env python3
"""Replay one committed proof with read-only tools and no network in the sandbox."""
import argparse
import json
from pathlib import Path
import re
import resource
import subprocess
import tempfile
import time

import yaml

from gate import CI, SUBMISSION, inspect, read_json, read_submission, require

STANDARDS = ["propext", "Quot.sound", "Classical.choice"]
MODULE = re.compile(r"[A-Za-z_][A-Za-z0-9_']*")


class Replay:
    def __init__(self, toolchain, mathlib):
        self.toolchain = toolchain.resolve()
        self.mathlib = mathlib.resolve() if mathlib else None
        self.deadline = time.monotonic() + 45 * 60

    def command(self, project, *args, stdout=subprocess.DEVNULL):
        command = ["bwrap", "--unshare-all", "--clearenv", "--die-with-parent", "--new-session",
                   "--ro-bind", "/usr", "/usr", "--ro-bind-try", "/lib", "/lib",
                   "--ro-bind-try", "/lib64", "/lib64", "--symlink", "usr/bin", "/bin",
                   "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                   "--ro-bind", str(self.toolchain), "/toolchain",
                   "--bind", str(project), "/work", "--chdir", "/work",
                   "--setenv", "HOME", "/tmp", "--setenv", "PATH", "/toolchain/bin:/usr/bin"]
        if self.mathlib:
            command += ["--ro-bind", str(self.mathlib), "/deps/mathlib"]
        seconds = self.deadline - time.monotonic()
        if seconds <= 0:
            raise subprocess.TimeoutExpired(args, 0)
        return subprocess.run(command + list(args), stdout=stdout, stderr=subprocess.DEVNULL,
                              timeout=seconds, check=False).returncode

    def project(self, directory, sources):
        directory.mkdir()
        roots = sorted({Path(name.split("/")[0]).stem for name in sources})
        require(all(MODULE.fullmatch(root) for root in roots), "Invalid Lean module name")
        require(not {"Mathlib", "Init", "Lean", "Lake", "Std"}.intersection(roots), "Reserved Lean module root")
        lakefile = ('name = "qunxing_replay"\n'
                    'defaultTargets = ["QunxingReplay"]\n'
                    '[[lean_lib]]\nname = "QunxingReplay"\n'
                    f'roots = {json.dumps(roots)}\n')
        if self.mathlib:
            lakefile += '\n[[require]]\nname = "mathlib"\npath = "/deps/mathlib"\n'
        (directory / "lakefile.toml").write_text(lakefile, encoding="utf-8")
        for name, data in sources.items():
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def export(self, directory, module, targets, output):
        if self.command(directory, "lake", "build") != 0:
            return False
        if module == "Solution" and self.command(directory, "lake", "env", "leanchecker", "--fresh", module) != 0:
            return False
        with output.open("xb") as file:
            status = self.command(directory, "lake", "env", "leanexport", module, "--", *targets, stdout=file)
        return status == 0 and output.stat().st_size > 0

    def run(self, files, names, definitions):
        # An output cap applies to files created by the candidate and the exporter.
        soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
        cap = 512 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_FSIZE, (cap if soft < 0 else min(soft, cap), hard))
        with tempfile.TemporaryDirectory(prefix="qunxing-replay-") as tmp:
            work = Path(tmp)
            challenge, solution, compare = (work / name for name in ("challenge", "solution", "compare"))
            compare.mkdir()
            self.project(challenge, {"Challenge.lean": files["Challenge.lean"]})
            self.project(solution, {name: data for name, data in files.items()
                                   if name.endswith(".lean") and name != "Challenge.lean"})
            targets = names + definitions
            if not self.export(challenge, "Challenge", targets, compare / "challenge.jsonl"):
                return "INCONCLUSIVE", "trusted_challenge_export_failed"
            if not self.export(solution, "Solution", targets, compare / "solution.jsonl"):
                return "INCONCLUSIVE", "solution_build_checker_or_export_failed"
            config = {
                "challenge_module": "Challenge", "solution_module": "Solution",
                "theorem_names": names, "definition_names": definitions, "permitted_axioms": STANDARDS,
                "external_kernels": {"nanoda": ["nanoda_bin"], "con-ron": ["con-ron"]},
            }
            (compare / "comparator.json").write_text(json.dumps(config), encoding="utf-8")
            (compare / "lakefile.toml").write_text('name = "qunxing_compare"\n', encoding="utf-8")
            code = self.command(compare, "lake", "comparator", "--config", "comparator.json",
                                "--challenge-from-export", "challenge.jsonl",
                                "--solution-from-export", "solution.jsonl")
            if code == 0:
                return "PASS", "lean_leanchecker_nanoda_con_ron"
            if code == 1:
                return "FAIL", "comparator_rejected"
            return "INCONCLUSIVE", "comparator_unavailable"


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("repo", type=Path)
    args.add_argument("commit")
    args.add_argument("submission")
    args.add_argument("toolchain", type=Path)
    args.add_argument("mathlib", type=Path)
    args.add_argument("report", type=Path)
    arg = args.parse_args()
    require(SUBMISSION.fullmatch(arg.submission), "Invalid submission directory")
    lock = read_json(CI / "locks.json")
    files = read_submission(arg.repo, arg.commit, arg.submission)
    report = inspect(files, arg.submission, lock)
    report["source_commit"] = arg.commit
    if report["status"] == "READY":
        manifest = yaml.safe_load(files["qunxing.yaml"])
        try:
            replay = Replay(arg.toolchain, arg.mathlib)
            status, reason = replay.run(files, manifest["claim"]["theorem_names"], manifest["claim"]["definition_names"])
        except subprocess.TimeoutExpired:
            status, reason = "INCONCLUSIVE", "time_limit"
        report.update(status=status, reason=reason)
    report["lean_replayed"] = report["status"] == "PASS"
    arg.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
