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
# Match the export roots used by Lean v4.35.0 Lake.CLI.Check for these axioms.
COMPARATOR_ROOTS = [
    *STANDARDS, "Quot", "Quot.mk", "Quot.lift", "Quot.ind",
    "Nat.add", "Nat.sub", "Nat.mul", "Nat.pow", "Nat.gcd", "Nat.div", "Nat.mod",
    "Nat.beq", "Nat.ble", "Nat.land", "Nat.lor", "Nat.xor", "Nat.shiftLeft", "Nat.shiftRight",
    "String.ofList", "Char.ofNat", "List", "eagerReduce", "Nat", "String", "String.mk",
    "Char", "optParam", "autoParam", "semiOutParam", "outParam",
]
MODULE = re.compile(r"[A-Za-z_][A-Za-z0-9_']*")
REJECTION = re.compile(
    r"^error: (?:Const not found in solution|Constant not found in solution|Const does not match |"
    r"Challenge and solution constant kind don't match|Challenge and solution theorem statement do not match|"
    r"Challenge constant is not a definition|Solution constant is not a definition|"
    r"Solution constant is not a theorem|Illegal axiom detected)|^Lean default kernel rejected ",
    re.MULTILINE,
)


class Replay:
    def __init__(self, toolchain, mathlib):
        self.toolchain = toolchain.resolve()
        self.mathlib = mathlib.resolve() if mathlib else None
        self.deadline = time.monotonic() + 45 * 60
        self.libraries = {}
        self.reserved = {"Mathlib", "Init", "Lean", "Lake", "Std"}
        if self.mathlib:
            # Expose prebuilt oleans without adding Lake targets that mutate the dependency tree.
            manifest = read_json(self.mathlib / "lake-manifest.json")
            packages = [Path(".")] + [
                Path(manifest["packagesDir"]) / package["name"] / (package["subDir"] or "")
                for package in manifest["packages"]
            ]
            for package in packages:
                relative = package / ".lake/build/lib/lean"
                library = self.mathlib / relative
                if library.is_dir():
                    for entry in library.iterdir():
                        self.libraries.setdefault(entry.name, Path("/deps/mathlib") / relative / entry.name)
                        if entry.is_dir() or entry.suffix == ".olean":
                            self.reserved.add(entry.stem)

    def command(self, project, *args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL):
        command = ["/usr/bin/bwrap", "--unshare-all", "--clearenv", "--die-with-parent", "--new-session",
                   "--ro-bind", "/usr", "/usr", "--ro-bind-try", "/lib", "/lib",
                   "--ro-bind-try", "/lib64", "/lib64", "--symlink", "usr/bin", "/bin",
                   "--ro-bind-try", "/etc/alternatives", "/etc/alternatives",
                   "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                   "--dir", "/home", "--dir", "/root", "--dir", "/run/user", "--dir", "/var",
                   "--ro-bind", str(self.toolchain), "/toolchain",
                   "--bind", str(project), "/work", "--chdir", "/work",
                   "--setenv", "HOME", "/tmp", "--setenv", "PATH", "/toolchain/bin:/usr/bin"]
        if self.mathlib:
            command += ["--ro-bind", str(self.mathlib), "/deps/mathlib"]
        seconds = self.deadline - time.monotonic()
        if seconds <= 0:
            raise subprocess.TimeoutExpired(args, 0)
        return subprocess.run(command + list(args), stdout=stdout, stderr=stderr,
                              timeout=seconds, check=False).returncode

    def project(self, directory, sources):
        directory.mkdir()
        roots = sorted({Path(name.split("/")[0]).stem for name in sources})
        require(all(MODULE.fullmatch(root) for root in roots), "Invalid Lean module name")
        require(not self.reserved.intersection(roots), "Reserved Lean module root")
        lakefile = ('name = "qunxing_replay"\n'
                    'defaultTargets = ["QunxingReplay"]\n'
                    '[[lean_lib]]\nname = "QunxingReplay"\n'
                    f'roots = {json.dumps(roots)}\n')
        (directory / "lakefile.toml").write_text(lakefile, encoding="utf-8")
        if self.libraries:
            artifacts = directory / ".lake/build/lib/lean"
            artifacts.mkdir(parents=True)
            for name, target in self.libraries.items():
                (artifacts / name).symlink_to(target)
        for name, data in sources.items():
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def export(self, directory, module, targets, output):
        if self.command(directory, "lake", "-f", "lakefile.toml", "build") != 0:
            return False
        if module == "Solution" and self.command(directory, "lake", "-f", "lakefile.toml", "env", "leanchecker", "--fresh", module) != 0:
            return False
        with output.open("xb") as file:
            status = self.command(directory, "lake", "-f", "lakefile.toml", "env", "leanexport", module, "--", *targets, stdout=file)
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
            targets = list(dict.fromkeys(names + definitions + COMPARATOR_ROOTS))
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
            transcript = work/"comparator.log"
            with transcript.open("xb") as output:
                code = self.command(compare, "lake", "comparator", "--config", "comparator.json",
                                    "--challenge-from-export", "challenge.jsonl",
                                    "--solution-from-export", "solution.jsonl",
                                    stdout=output, stderr=subprocess.STDOUT)
            if code == 0:
                return "PASS", "lean_leanchecker_nanoda_con_ron"
            with transcript.open("r", encoding="utf-8", errors="replace") as output:
                if code == 1 and any(REJECTION.search(line) for line in output):
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
