# Regenerates the offline backup transcripts. Run from the folder above deploysure/. Needs no key and no internet:
# without GROQ_API_KEY every AI step uses its deterministic default, and the trace says so.
$py = "deploysure\.venv\Scripts\python.exe"
$env:GROQ_API_KEY = ""
foreach ($v in "v2.1", "v2.2") {
    & $py -m deploysure.cli $v 2>&1 | Out-File "deploysure\backup\project_$v.txt" -Encoding utf8
}
foreach ($pair in @(("v1.1", "v1.2", "safe"), ("v1.2", "v2.0-backend-bug", "backend-bug"),
                    ("v1.2", "v2.1-frontend-bug", "frontend-bug"), ("v1.2", "v2.2-contract-break", "contract-break"))) {
    & $py -m deploysure.app_cli deploysure\demo_apps\tinyshop $pair[0] $pair[1] 2>&1 | Out-File "deploysure\backup\app_$($pair[2]).txt" -Encoding utf8
}
