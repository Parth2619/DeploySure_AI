"""Builds the git repo that you connect to DeploySure on stage:  python make_stage_repo.py

It copies stage_app/ into presentation/stage_repo/ and gives it three good commits (v1.0, v1.1, v1.2). The buggy file
stays outside the repo in stage_app/bug_variants/ until you copy it in. Running this again resets the demo.
Needs only git and Python. It has no link to the DeploySure code.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "stage_app"
DEST = HERE / "stage_repo"
SKIP = {"bug_variants", "__pycache__", ".pytest_cache"}

# Older texts, so the history has real changes. Each pair is (old text, final text) in one file.
V1_1_FRONTEND = ("frontend/index.html", '<button id="quote">Get price</button>', '<button id="quote">Calculate price</button>')
V1_2_BACKEND = [
    ("backend/app.py", '"final_price": final}', '"final_price": final,\n            "savings": round(body.price - final, 2)}'),
    ("tests/test_api.py", 'data["final_price"] == 180.0', 'data["final_price"] == 180.0 and data["savings"] == 20.0'),
]


def git(*args: str, date: str | None = None) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "PriceRight Dev", "GIT_AUTHOR_EMAIL": "dev@priceright.example",
           "GIT_COMMITTER_NAME": "PriceRight Dev", "GIT_COMMITTER_EMAIL": "dev@priceright.example"}
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    done = subprocess.run(["git", "-C", str(DEST), *args], capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
    if done.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def final_files() -> dict[str, str]:
    files = {}
    for path in sorted(SOURCE.rglob("*")):
        relative = path.relative_to(SOURCE)
        if path.is_file() and not SKIP & set(relative.parts):
            files[relative.as_posix()] = path.read_text(encoding="utf-8")
    return files


def replace(files: dict[str, str], name: str, old: str, new: str) -> dict[str, str]:
    assert old in files[name], f"{old!r} not found in {name}"
    return {**files, name: files[name].replace(old, new)}


def commit(files: dict[str, str], message: str, tag: str, day: int) -> None:
    for name, text in files.items():
        (DEST / name).parent.mkdir(parents=True, exist_ok=True)
        (DEST / name).write_text(text, encoding="utf-8", newline="\n")
    git("add", "-A")
    git("commit", "-m", message, date=f"2026-10-{day:02d}T10:00:00+00:00")
    git("tag", tag)


def main() -> None:
    if DEST.exists():
        if not (DEST / ".git").is_dir():
            sys.exit(f"{DEST} exists and is not a repo made by this script, so it was left alone")
        shutil.rmtree(DEST, onerror=lambda func, path, _: (os.chmod(path, 0o700), func(path)))  # .git files are read-only on Windows
    DEST.mkdir()
    git("init", "-b", "main")
    git("config", "core.autocrlf", "false")  # a copied file must be committed exactly as it is
    v1_2 = final_files()
    v1_1 = v1_2
    for name, old, new in V1_2_BACKEND:
        v1_1 = replace(v1_1, name, new, old)
    v1_0 = replace(v1_1, V1_1_FRONTEND[0], V1_1_FRONTEND[2], V1_1_FRONTEND[1])
    commit(v1_0, "Initial PriceRight: discount calculator", "v1.0", 1)
    commit(v1_1, "Reword the calculate button", "v1.1", 2)
    commit(v1_2, "Report the savings in the quote", "v1.2", 3)
    print(f"Created {DEST} with 3 commits (v1.0, v1.1, v1.2).")
    print("Connect that folder in DeploySure, then make the buggy commit as described in README.md.")


if __name__ == "__main__":
    main()
