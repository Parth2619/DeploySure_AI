import pytest

from deploysure.demo_apps import build_tinyshop
from deploysure.models import llm
from tests import fake_llm


@pytest.fixture(autouse=True)
def no_real_ai(request, monkeypatch, tmp_path):
    """Tests never call Groq. A test marked real_llm opts out so it can exercise the real client code."""
    monkeypatch.setattr(llm, "ENV_FILE", tmp_path / "no.env")  # a real .env on this machine must not leak into tests
    if request.node.get_closest_marker("real_llm") is None:
        # Looked up at call time, so a test can replace fake_llm.answer to simulate a different model.
        monkeypatch.setattr(llm, "_groq_answer", lambda prompt, schema: fake_llm.groq_answer(prompt, schema), raising=False)


@pytest.fixture(scope="session")
def tinyshop(tmp_path_factory):
    """The TinyShop demo repo, built once per test run. Returns (repo path, {tag: sha})."""
    repo = tmp_path_factory.mktemp("tinyshop_repo") / "tinyshop"
    return repo, build_tinyshop.build(repo)
