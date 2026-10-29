# Stage demo notes: Connect app

## 60 second pitch

"Most release tools check whether tests pass. DeploySure takes a whole app, the frontend and the backend together,
watches its git history and, when a new commit arrives, runs the old and the new version side by side. AI agents write
the checks. Then fixed rules decide whether it is safe to ship and which layer is at fault: frontend, backend or the
connection between them. A Critic agent checks the decision before it is final."

## Script

1. **Connect:** click Connect app, enter PriceRight and its folder. "It only reads the repo. It never changes it."
2. **Watch on:** tick the checkbox. "From now on, a new commit is analyzed by itself. This is polling while the page is open, not a git hook."
3. **Show the app:** "A discount calculator. Page on one side, FastAPI backend on the other. Three good commits."
4. **The developer's change:** run the two commands (copy the buggy file, then git commit). "One file in the backend. It looks like a harmless simplification."
5. **While the agents tick:** planner, change scan, check writer (AI), differential run, layer attribution, risk, decision, Critic.
6. **Read the result:** BLOCK, risk 83, Backend highlighted. "A 10 percent discount on 200 used to return 180. Now the server errors. The frontend did not change, so the broken page is a symptom, and the fault is in the backend."
7. **Limits:** "Evidence based. It only finds what its checks try. It understands FastAPI and Flask backends with plain frontends. It is not a guarantee of production safety."

## Likely questions

- **Is the BLOCK scripted?** No. The commit before the swap analyzes as DEPLOY. After the swap the old and new app give different answers, and that difference drives the result.
- **How does it know it is the backend and not the frontend?** It compares what changed: only a backend file changed, the API answer broke, and the page failure is the same request failing. If a page file had changed and called a wrong route, it would say frontend. If the API renamed a field the page still reads, it says connection.
- **What does the AI do, and what is plain code?** The AI writes the plan, the checks and the wording. Scanning, running both versions, layer attribution, the risk score and the Critic's rule floor are code.
- **What if the AI is wrong or offline?** The Critic enforces a rule floor in code: the AI can be more cautious, never less. Offline, the same result comes from fixed checks. The trace says "AI not used".
- **Does it run my code?** Yes, in a temporary copy on this laptop, with a limited environment. That is why it is demoed on dummy apps only.
- **Why not just run the unit tests?** The app's tests may not cover the page or the connection. Here they would catch the bug, but in the TinyShop demo they pass on every broken commit.

## If something goes wrong

- The server must run from `D:\STUDY\FAAI\Project\DeploySure AI` with `deploysure.server:app`.
- Page says another analysis is running: wait for it to finish.
- Reset the repo with `make_stage_repo.py` and remove the app in DeploySure first.
- Backup transcripts of full runs are in `deploysure\backup\`.
