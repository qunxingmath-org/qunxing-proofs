#!/usr/bin/env bash
set -euo pipefail

# Ubuntu 24.04 requires a per-program user namespace rule for this sandbox.
if [[ "$(sysctl -n kernel.apparmor_restrict_unprivileged_userns 2>/dev/null || echo 0)" == 1 ]]; then
  sudo apparmor_parser -r <<'PROFILE'
abi <abi/4.0>,
profile qunxing-ci-bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
}
PROFILE
fi
