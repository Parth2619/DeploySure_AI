"""Web routes for app mode: connect a git repo, see its commit timeline, analyze a change, read saved results."""
import string
import threading
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from deploysure import demo_apps
from deploysure.app_api import AppRequestError, check_app_request, stream_app_validation
from deploysure.demo_apps import build_tinyshop
from deploysure.tools import app_store
from deploysure.tools.project_store import ProjectError
from deploysure.web_common import require_ui_header, sse

router = APIRouter()
DEMO_APPS = Path(demo_apps.__file__).resolve().parent
EXAMPLES = [
    ("tinyshop", "TinyShop, full history", "Three broken commits sit on their own branches. Analyze any of them against v1.2."),
    ("tinyshop_live", "TinyShop, live", "Only the good history. Turn Watch on, simulate a developer commit, and DeploySure analyzes it by itself."),
]
MAX_FOLDERS = 500
# An analysis starts two copies of the app and a browser, so only one runs at a time.
_busy = threading.Lock()


class NewApp(BaseModel):
    name: str = ""
    repo_path: str = ""  # a folder on the computer the server runs on, or
    repo_url: str = ""   # a public GitHub link that the server downloads


class WatchBody(BaseModel):
    watch: bool


class AnalyzeBody(BaseModel):
    old: str
    new: str


class DemoCommit(BaseModel):
    change: str


def _events(app_id: str, repo: str, old: str, new: str) -> Iterator[str]:
    if not _busy.acquire(blocking=False):
        yield sse({"node": "error", "status": "failed", "state_update": {"error": "another app analysis is running. Wait for it to finish."}})
        return
    steps = []  # each agent's input, output and AI calls, kept with the saved analysis so the pipeline view works later too
    try:
        for event in stream_app_validation(repo, old, new):
            if event["node"] == "final":
                event["final_report"]["steps"] = steps
                app_store.save_analysis(app_id, event["final_report"])
            else:
                steps.append({"node": event["node"], "timestamp": event["timestamp"], "output": event["state_update"], **event["io"]})
            yield sse(event)
    except Exception as err:  # the stream is already open, so report the failure as an event
        yield sse({"node": "error", "status": "failed", "state_update": {"error": str(err) or type(err).__name__}})
    finally:
        _busy.release()


@router.get("/app-examples")
def examples() -> list[dict]:
    """The demo repos that exist on this machine, so the UI can offer them in the Connect dialog."""
    return [{"name": name, "path": str(DEMO_APPS / folder), "note": note} for folder, name, note in EXAMPLES
            if (DEMO_APPS / folder / ".git").exists()]


@router.get("/browse-folders", dependencies=[Depends(require_ui_header)])
def browse_folders(path: str = "") -> dict:
    """Lists the sub-folders of a folder on this computer, for the Browse list in the Connect dialog (names only, no file contents).
    With no path it lists the drives and the home folder. The server only runs locally."""
    if not path:
        starts = [Path(f"{letter}:\\") for letter in string.ascii_uppercase if Path(f"{letter}:\\").exists()] + [Path.home()]
        return {"path": "", "parent": None, "is_repo": False, "folders": [{"name": str(p), "path": str(p)} for p in starts]}
    here = Path(path).expanduser()
    if not here.is_dir():
        raise ProjectError(f"the folder {here} does not exist")
    try:
        children = sorted((c for c in here.iterdir() if c.is_dir() and not c.name.startswith((".", "$"))), key=lambda c: c.name.lower())
    except OSError:
        raise ProjectError(f"the folder {here} cannot be opened", 403)
    here = here.resolve()
    return {"path": str(here), "parent": str(here.parent) if here.parent != here else "", "is_repo": (here / ".git").exists(),
            "folders": [{"name": c.name, "path": str(c)} for c in children[:MAX_FOLDERS]]}


@router.post("/apps/{app_id}/demo-commit", status_code=201, dependencies=[Depends(require_ui_header)])
def demo_commit(app_id: str, body: DemoCommit) -> dict:
    """Plays the developer: adds one prepared change as a new commit. Only allowed inside our own demo_apps folder."""
    repo = Path(app_store.get_app(app_id)["app"]["repo_path"]).resolve()
    if DEMO_APPS.resolve() not in repo.parents:
        raise ProjectError("simulated commits are only allowed in the demo apps folder, never in your own repos", 403)
    try:
        sha = build_tinyshop.push_commit(repo, body.change)
    except ValueError as err:
        raise ProjectError(str(err))
    return {"sha": sha, "message": build_tinyshop.LIVE_CHANGES[body.change][1]}


@router.get("/apps")
def apps() -> list[dict]:
    return app_store.list_apps()


@router.post("/apps", status_code=201)
def new_app(body: NewApp) -> dict:
    if bool(body.repo_path.strip()) == bool(body.repo_url.strip()):
        raise ProjectError("give either a repo folder or a GitHub link, not both and not neither")
    if body.repo_url.strip():
        return app_store.connect_github(body.name, body.repo_url)
    if not body.name.strip():
        raise ProjectError("give the app a name")
    return app_store.connect_app(body.name, body.repo_path)


@router.get("/apps/{app_id}")
def app_detail(app_id: str) -> dict:
    detail = app_store.get_app(app_id)
    # The UI only offers "simulate a commit" for demo repos, where the server allows it.
    return {**detail, "demo": DEMO_APPS.resolve() in Path(detail["app"]["repo_path"]).resolve().parents}


@router.delete("/apps/{app_id}", status_code=204)
def remove_app(app_id: str) -> None:
    app_store.delete_app(app_id)


@router.put("/apps/{app_id}/watch")
def watch(app_id: str, body: WatchBody) -> dict:
    app_store.set_watch(app_id, body.watch)
    return {"watch": body.watch}


@router.get("/apps/{app_id}/analyses/{old_sha}/{new_sha}")
def saved_analysis(app_id: str, old_sha: str, new_sha: str) -> dict:
    return app_store.load_analysis(app_id, old_sha, new_sha)


@router.post("/apps/{app_id}/analyze", dependencies=[Depends(require_ui_header)])
def analyze_app(app_id: str, body: AnalyzeBody) -> StreamingResponse:
    app = app_store.get_app(app_id)["app"]
    try:
        check_app_request(app["repo_path"], body.old, body.new)  # raises before the stream opens, so the UI gets a real status
    except AppRequestError as err:
        raise ProjectError(str(err))
    return StreamingResponse(_events(app_id, app["repo_path"], body.old, body.new), media_type="text/event-stream")
