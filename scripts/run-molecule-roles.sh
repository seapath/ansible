#!/usr/bin/env bash
set -euo pipefail

# Directory containing the Ansible roles
ROLES_DIR="roles"

# Discover all subdirectories inside roles/
mapfile -t role_list < <(find "$ROLES_DIR" -mindepth 1 -maxdepth 1 -type d 2>/dev/null || true)

any=0
failed=0

for r in "${role_list[@]}"; do
  [[ -d "$r" ]] || continue

  # Skip roles that do not contain a molecule/ directory
  if [[ ! -d "$r/molecule" ]]; then
    echo "==> SKIP (no molecule/ directory): $r"
    continue
  fi

  any=1
  echo "==> RUN  (all scenarios): $r"

  # Run all Molecule scenarios for the role
  (cd "$r" && molecule test --all) || failed=1
done

# Informational message if no roles with molecule/ were found
if [[ "$any" -eq 0 ]]; then
  echo "No roles with a molecule/ directory found under $ROLES_DIR/"
fi

# Exit with non-zero status if at least one role failed
exit "$failed"
