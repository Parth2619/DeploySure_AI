"""Planner: turns the release notes (and any Critic complaint) into a task list. Uses the LLM."""
from pydantic import BaseModel, Field

from deploysure.models.llm import PLAN, ask
from deploysure.orchestration.state import ReleaseState
from deploysure.tools.code_reader import load_release


class Plan(BaseModel):
    tasks: list[str] = Field(min_length=1)


def planner(state: ReleaseState) -> dict:
    release = load_release(state["release_id"])
    prompt = (
        "You plan the safety check of a software release. Reply as JSON: {\"tasks\": [5 to 8 short steps]}.\n"
        f"Release {release['release_id']}: {release['title']}. Notes: {release['notes']}\n"
        f"Critic feedback from the previous attempt: {state.get('feedback') or 'none'}"
    )
    answer, fallback = ask(prompt, Plan, task="planner", default={"tasks": PLAN})
    note = " (model output invalid, used fixed plan)" if fallback else ""
    return {
        "tasks": answer["tasks"],
        "baseline": release["baseline"],
        "trace": [f"planner: planned {len(answer['tasks'])} tasks for {state['release_id']}{note}"],
    }
