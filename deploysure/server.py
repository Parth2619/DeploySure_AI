"""Optional HTTP layer for the UI. Run from the folder above this one:

    uvicorn deploysure.server:app --port 8000
    curl -N -X POST http://localhost:8000/analyze/v2.2
"""
import json
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from deploysure.api import check_release, list_releases, stream_release_validation

app = FastAPI(title="DeploySure AI")
# Local UI only: any port on localhost.
app.add_middleware(CORSMiddleware, allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
                   allow_methods=["*"], allow_headers=["*"])


def sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _events(release_id: str) -> Iterator[str]:
    try:
        for event in stream_release_validation(release_id):
            yield sse(event)
    except Exception as err:  # the stream is already open, so report the failure as an event
        yield sse({"node": "error", "status": "failed", "state_update": {"error": str(err)}})


@app.get("/releases")
def releases() -> list[dict]:
    return list_releases()


@app.post("/analyze/{release_id}")
def analyze(release_id: str) -> StreamingResponse:
    try:
        check_release(release_id)
    except (ValueError, FileNotFoundError) as err:
        raise HTTPException(status_code=404, detail=str(err))
    return StreamingResponse(_events(release_id), media_type="text/event-stream")


# Mounted last so the API routes above win. Serves the UI at http://localhost:8000/
app.mount("/", StaticFiles(directory=Path(__file__).parent / "ui", html=True), name="ui")
