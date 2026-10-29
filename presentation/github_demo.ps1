# Plays the developer on GitHub for the PriceRight demo.
#   powershell -File presentation\github_demo.ps1 bug     pushes the buggy commit to main (main moves forward by one commit)
#   powershell -File presentation\github_demo.ps1 reset   puts main back on the three good commits (v1.2)
# It uses a temporary clone, so no folder of yours is touched. Needs git logged in to GitHub, as on this laptop.
param([Parameter(Mandatory)][ValidateSet("bug", "reset")][string]$Action)
$url = "https://github.com/Parth2619/priceright-demo.git"
$tmp = Join-Path $env:TEMP "priceright_push"

# git writes its progress to stderr, which PowerShell would show as red errors, so print it as plain text and check the exit code.
function Invoke-Git {
    & git.exe @args 2>&1 | ForEach-Object { "$_" }
    if ($LASTEXITCODE -ne 0) { throw "git $($args[0]) failed" }
}

Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
try {
    Invoke-Git clone -q $url $tmp
    if ($Action -eq "bug") { Invoke-Git -C $tmp push origin "refs/remotes/origin/buggy-release:refs/heads/main" }
    else { Invoke-Git -C $tmp push --force origin "v1.2^{commit}:refs/heads/main" }   # the force is safe: it only moves main back to the demo's own start
    Write-Host "Done: $Action"
}
finally { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }
