import json

import pytest

pytest.importorskip("fastapi")  # server.py is optional

from fastapi import HTTPException

from deploysure.server import analyze, releases, sse


def test_sse_frame_format():
    frame = sse({"node": "critic"})
    assert frame.startswith("data: ") and frame.endswith("\n\n")
    assert json.loads(frame[6:]) == {"node": "critic"}


def test_releases_endpoint_lists_both():
    assert {r["release_id"] for r in releases()} == {"v2.1", "v2.2"}


def test_unknown_release_is_404_before_streaming():
    with pytest.raises(HTTPException) as err:
        analyze("v9.9")
    assert err.value.status_code == 404
