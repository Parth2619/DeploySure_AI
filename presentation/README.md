# Presentation demos

Two demos, independent of each other and of the DeploySure code:

| Folder | What it is | How you show it |
|---|---|---|
| `stage_app/` and `make_stage_repo.py` | A small web app (frontend + backend) called PriceRight, built for **Connect app** | DeploySure web page |
| `terminal_demo/` | A pricing module with its own deployment gate, run in the terminal | PowerShell, see `terminal_demo\README.md` |

## Connect app demo (on stage)

PriceRight is a discount calculator: a page with a price and a discount box, and a FastAPI backend (`POST /api/quote`).
The one file you swap is `backend/pricing.py`. The buggy version forgets to divide the percentage by 100.

### Before the presentation (once, and again to reset)

Run from `D:\STUDY\FAAI\Project\DeploySure AI`:

```powershell
deploysure\.venv\Scripts\python presentation\make_stage_repo.py
deploysure\.venv\Scripts\python -m uvicorn deploysure.server:app --port 8000
```

The first command builds a git repo in `presentation\stage_repo` with three good commits. Running it again resets
the demo (it only deletes that folder). The second starts DeploySure. Your Groq key is read from `deploysure\.env`.

### On stage

1. Open http://localhost:8000 and click **Connect app**.
2. Type the name `PriceRight` and the folder `D:\STUDY\FAAI\Project\DeploySure AI\presentation\stage_repo`, then click **Connect app**.
3. On the app page, tick **Analyze new commits automatically**.
4. Say: "This is a good, working version. A developer now changes one file." In a PowerShell window run:

```powershell
Copy-Item .\presentation\stage_app\bug_variants\pricing_buggy.py .\presentation\stage_repo\backend\pricing.py -Force
git -C .\presentation\stage_repo commit -am "Simplify the discount formula"
```

5. Within a few seconds the page shows the new commit, the agents tick through by themselves, and the result is
   **BLOCK**, risk about 83, with the **Backend** box highlighted and the reason "status changed from 200 to 500".

If you want to show the good case first, use the **Analyze** button on the commit "Report the savings in the quote":
it should come out DEPLOY with no faulty layer.

### Option A (recommended): connect the GitHub link, then push the bug

The repo https://github.com/Parth2619/priceright-demo is public. `main` must hold the three good commits (v1.0 to v1.2).
DeploySure downloads it once and checks GitHub every few seconds, so nobody pulls anything by hand. This works the same
on your laptop and on the AWS server.

1. In DeploySure click **Connect app**, type `https://github.com/Parth2619/priceright-demo` in **GitHub link**, click **Connect app**.
2. Tick **Analyze new commits automatically**.
3. Play the developer by pushing the buggy commit to `main` (from your laptop, in PowerShell):

```powershell
powershell -File presentation\github_demo.ps1 bug
```

4. Within about 15 seconds the new commit appears on the timeline and is analyzed: BLOCK, risk about 83, backend.
5. To run the demo again, restore `main` to the three good commits, then remove and reconnect the app in DeploySure:

```powershell
powershell -File presentation\github_demo.ps1 reset
```

`reset` force-pushes `main` back to v1.2. That is safe here because it only rewinds the demo's own history. Do not edit
files in the GitHub web page by hand, because that adds commits to `main` that are not part of the demo.

### Option B: pull the buggy commit from GitHub (no file copying)

The same app is on GitHub as a private repo: https://github.com/Parth2619/priceright-demo
`main` has the three good commits. The branch `buggy-release` is `main` plus one commit, the buggy `pricing.py`.

Before the presentation, clone only `main` (so the buggy commit is not in your timeline yet) and connect that clone:

```powershell
git clone --single-branch --branch main https://github.com/Parth2619/priceright-demo.git D:\demo\priceright
```

In DeploySure: **Connect app**, **Browse** to `D:\demo\priceright`, **Connect app**, tick **Analyze new commits automatically**.

On stage, pull the buggy release:

```powershell
git -C D:\demo\priceright pull origin buggy-release
```

The pull moves `main` forward by one commit. DeploySure sees the new commit within seconds, analyzes it, and shows
BLOCK, risk about 83, backend. To repeat the demo, delete `D:\demo\priceright`, clone again and remove the app in
DeploySure first. The demo laptop needs git and a GitHub login that can read the private repo.
Nothing from `deploysure\` (including `.env`) is in that repo, only the PriceRight app.

### What the audience sees

- The page, the API and the tests all look normal in the first three commits.
- After the one-file change, the old and the new version run side by side. The same request that returned 180 now returns a server error, and the page itself breaks (the button no longer shows a price).
- DeploySure names the layer: Backend. The frontend did not change, so the broken page is treated as a symptom.
- The AI writes the checks and the wording. The layer, the risk score and the BLOCK rule are plain code.

### Reset after the demo

```powershell
deploysure\.venv\Scripts\python presentation\make_stage_repo.py
```

Then remove the app in DeploySure (**Remove this app** on the left of the app page) before connecting again, or connect it under a new name.

### If the internet or Groq fails

Everything still works. The AI steps use their fixed defaults (the trace says "AI not used") and the result is the same
BLOCK, backend, risk 83. This was tested with the network blocked.

### What the app's own tests do

`stage_app\tests` has a few ordinary tests. They pass on the three good commits and fail after the swap, which is fine.
DeploySure does not depend on them: it compares what the old and new app actually do.
