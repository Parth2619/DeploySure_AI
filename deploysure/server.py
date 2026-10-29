"""Optional HTTP layer and UI host. Run from the folder above this one:

    uvicorn deploysure.server:app --port 8000        then open http://localhost:8000
    curl -N -X POST -H "X-DeploySure: 1" http://localhost:8000/projects/demo-shop/versions/v2.2/analyze
"""
from pathlib import Path
from typing import Iterator

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from deploysure.api import check_release, stream_release_validation
from deploysure.tools import project_store, test_cases
from deploysure.tools.project_store import ProjectError
from deploysure.web_common import require_ui_header, sse
from deploysure import server_apps

class UiFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"  # revalidate every time, so an edited page or script shows on a normal refresh
        return response


app = FastAPI(title="DeploySure AI")
# Local UI only: any port on localhost. Pytest runs project code, so never expose this server to a network.
app.add_middleware(CORSMiddleware, allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
                   allow_methods=["*"], allow_headers=["*"])
# Refuses requests whose Host is not local, which also stops DNS rebinding tricks.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])


class NewProject(BaseModel):
    name: str
    folder_path: str
    version: str = "v1.0"
    critical_modules: list[str] = []


class NewVersion(BaseModel):
    version: str
    folder_path: str
    notes: str = ""


class NewSource(BaseModel):
    source: str


class NewTest(BaseModel):
    title: str
    source: str
    critical: bool = False


@app.exception_handler(ProjectError)
def handle_project_error(request: Request | None, err: ProjectError) -> JSONResponse:
    return JSONResponse(status_code=err.status, content={"detail": str(err)})


def _events(project_id: str, version: str) -> Iterator[str]:
    try:
        for event in stream_release_validation(version, project_id):
            yield sse(event)
    except Exception as err:  # the stream is already open, so report the failure as an event
        yield sse({"node": "error", "status": "failed", "state_update": {"error": str(err) or type(err).__name__}})


@app.get("/projects")
def projects() -> list[dict]:
    return project_store.list_projects()


@app.post("/projects", status_code=201)
def new_project(body: NewProject) -> dict:
    return project_store.create_project(body.name, body.folder_path, body.version, body.critical_modules)


@app.get("/projects/{project_id}")
def project(project_id: str) -> dict:
    return project_store.get_project(project_id)


@app.post("/projects/{project_id}/versions", status_code=201)
def new_version(project_id: str, body: NewVersion) -> dict:
    return project_store.add_version(project_id, body.version, body.folder_path, body.notes)


@app.get("/projects/{project_id}/tests")
def tests_list(project_id: str) -> list[dict]:
    return test_cases.list_test_cases(project_id)


@app.post("/projects/{project_id}/tests", status_code=201)
def new_test(project_id: str, body: NewTest) -> dict:
    return test_cases.add_test_case(project_id, body.title, body.source, body.critical)


@app.get("/projects/{project_id}/test-files/{file}")
def test_file(project_id: str, file: str) -> dict:
    return test_cases.read_test_file(project_id, file)


@app.put("/projects/{project_id}/test-files/{file}")
def edit_test_file(project_id: str, file: str, body: NewSource) -> dict:
    return test_cases.save_test_file(project_id, file, body.source)


@app.get("/projects/{project_id}/all-tests")
def all_tests(project_id: str) -> list[dict]:
    return test_cases.list_all_tests(project_id)


@app.put("/projects/{project_id}/tests/{case_id}")
def edit_test(project_id: str, case_id: int, body: NewTest) -> dict:
    return test_cases.update_test_case(project_id, case_id, body.title, body.source, body.critical)


@app.delete("/projects/{project_id}/tests/{case_id}", status_code=204)
def remove_test(project_id: str, case_id: int) -> None:
    test_cases.delete_test_case(project_id, case_id)


@app.post("/projects/{project_id}/versions/{version}/analyze", dependencies=[Depends(require_ui_header)])
def analyze(project_id: str, version: str) -> StreamingResponse:
    check_release(version, project_id)  # raises before the stream opens, so the UI gets a real error status
    return StreamingResponse(_events(project_id, version), media_type="text/event-stream")


app.include_router(server_apps.router)


# Mounted last so the API routes above win. Serves the UI at http://localhost:8000/
app.mount("/", UiFiles(directory=Path(__file__).parent / "ui", html=True), name="ui")
