#!/usr/bin/env bash
# Recreate the two demo repos from the template: guarded (Laya hook + deny rules) and unguarded.
set -euo pipefail
cd "$(dirname "$0")"
rm -rf demo-repo demo-repo-unguarded
cp -a demo-template demo-repo
cp -a demo-template demo-repo-unguarded
rm -rf demo-repo-unguarded/.claude
for d in demo-repo demo-repo-unguarded; do
  (cd "$d" && git init -q && git add -A && git -c user.name=demo -c user.email=demo@example.com commit -qm "Initial import")
done
echo "Ready: demo-repo (guarded) and demo-repo-unguarded"
