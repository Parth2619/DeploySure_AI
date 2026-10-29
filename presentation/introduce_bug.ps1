# Plays the developer for the demo: puts the buggy pricing.py into the PriceRight repo and commits it.
# Run from anywhere:  powershell -File presentation\introduce_bug.ps1
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Join-Path $here "stage_repo"
Copy-Item (Join-Path $here "stage_app\bug_variants\pricing_buggy.py") (Join-Path $repo "backend\pricing.py") -Force  # the copy must be named pricing.py
git -C $repo commit -am "Simplify the discount formula"
