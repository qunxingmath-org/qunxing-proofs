#!/usr/bin/env python3
"""Run a positive and a well-typed negative Lean fixture on the CI runner."""
from pathlib import Path
import subprocess
import sys

from replay import Replay

class FixtureReplay(Replay):
    def command(self, project, *args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL):
        print("Fixture command:", *args, flush=True)
        status = super().command(project, *args,
                                 stdout=None if stdout == subprocess.DEVNULL else stdout,
                                 stderr=None if stderr == subprocess.DEVNULL else stderr)
        if status != 0 and "comparator" in args:
            print(Path(stdout.name).read_text(encoding="utf-8", errors="replace")[:4000], flush=True)
        print("Fixture exit status:", status, flush=True)
        return status


chain = Path(sys.argv[1])
proof = {
    "Challenge.lean": b"theorem qxSample : 1 + 1 = 2 := by sorry\n",
    "Solution.lean": b"theorem qxSample : 1 + 1 = 2 := rfl\n",
}
accepted = FixtureReplay(chain, None).run(proof, ["qxSample"], [])
print("Matching theorem:", accepted)
assert accepted[0] == "PASS"

proof["Solution.lean"] = b"theorem qxSample : 1 + 2 = 3 := rfl\n"
rejected = FixtureReplay(chain, None).run(proof, ["qxSample"], [])
print("Different statement:", rejected)
assert rejected[0] == "FAIL"
