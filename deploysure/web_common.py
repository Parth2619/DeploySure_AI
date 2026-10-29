"""Small pieces shared by the web routes: the Server-Sent Events frame and the header guard for analyze calls."""
import json

from fastapi import Header, HTTPException


def sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def require_ui_header(x_deploysure: str | None = Header(default=None)) -> None:
    """The analyze calls have no body, so a web page on another site could fire them. A custom header blocks that."""
    if not x_deploysure:
        raise HTTPException(status_code=403, detail="Send the X-DeploySure header. The UI does this for you.")
