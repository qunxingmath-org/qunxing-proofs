#!/usr/bin/env python3
"""Run a positive and a well-typed negative Lean fixture on the CI runner."""
from pathlib import Path
import sys

from replay import Replay

chain = Path(sys.argv[1])
proof = {
    "Challenge.lean": b"theorem qxSample : 1 + 1 = 2 := by sorry\n",
    "Solution.lean": b"theorem qxSample : 1 + 1 = 2 := rfl\n",
}
accepted = Replay(chain, None).run(proof, ["qxSample"], [])
print("Matching theorem:", accepted)
assert accepted[0] == "PASS"

proof["Solution.lean"] = b"theorem qxSample : 1 + 2 = 3 := rfl\n"
rejected = Replay(chain, None).run(proof, ["qxSample"], [])
print("Different statement:", rejected)
assert rejected[0] == "FAIL"
