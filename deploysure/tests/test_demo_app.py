"""The TinyShop demo repo: its git history and what each commit really does when the app runs."""
import contextlib
import io
import socket
import subprocess
import sys
import tarfile
import time

import httpx
import pytest

from deploysure.demo_apps import build_tinyshop as shop

ORDER = {"items": [{"product_id": 1, "quantity": 2}, {"product_id": 2, "quantity": 1}]}  # 2 x 4.50 + 1.25 = 10.25
TAGS = ["v1.0", "v1.1", "v1.2", "v2.0-backend-bug", "v2.1-frontend-bug", "v2.2-contract-break"]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    repo = tmp_path_factory.mktemp("repo") / "tinyshop"
    return repo, shop.build(repo), tmp_path_factory.mktemp("checkouts")


def checkout(repo, tag, into):
    data = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", tag], capture_output=True, check=True, timeout=60).stdout
    root = into / tag
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        archive.extractall(root)
    return root


@contextlib.contextmanager
def serve(root):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app:app", "--port", str(port), "--log-level", "warning"],
                            cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                if httpx.get(base + "/api/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.25)
        else:
            raise AssertionError("the app did not start")
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def run_app(built, tag):
    repo, _, into = built
    root = checkout(repo, tag, into)
    return root, serve(root)


def changed(repo, a, b):
    out = subprocess.run(["git", "-C", str(repo), "diff", "--name-only", a, b], capture_output=True, text=True, check=True).stdout
    return sorted(out.split())


# ---------- history ----------

def test_history_has_the_expected_tags_and_parents(built):
    repo, shas, _ = built
    assert sorted(shas) == sorted(TAGS)
    parent = lambda tag: subprocess.run(["git", "-C", str(repo), "rev-parse", tag + "^"], capture_output=True, text=True, check=True).stdout.strip()
    assert parent("v1.1") == shas["v1.0"] and parent("v1.2") == shas["v1.1"]
    assert all(parent(t) == shas["v1.2"] for t in TAGS[3:])  # each break is one commit on top of the last good version


@pytest.mark.parametrize("a,b,files", [
    ("v1.0", "v1.1", ["frontend/app.js", "frontend/style.css"]),
    ("v1.1", "v1.2", [".env.example", "backend/app.py"]),
    ("v1.2", "v2.0-backend-bug", ["backend/app.py"]),
    ("v1.2", "v2.1-frontend-bug", ["frontend/app.js"]),
    ("v1.2", "v2.2-contract-break", ["backend/app.py", "tests/test_api.py"]),
])
def test_each_commit_touches_only_the_files_it_should(built, a, b, files):
    assert changed(built[0], a, b) == files


def test_the_build_is_deterministic(tmp_path):
    assert shop.build(tmp_path / "one") == shop.build(tmp_path / "two")


def test_main_is_a_clean_checkout(built):
    out = subprocess.run(["git", "-C", str(built[0]), "status", "--short"], capture_output=True, text=True, check=True).stdout
    assert out.strip() == ""


# ---------- behaviour of each commit ----------

def test_v1_0_works(built):
    root, server = run_app(built, "v1.0")
    with server as base:
        assert httpx.get(base + "/api/products").json()[0] == {"id": 1, "name": "Notebook", "price": 4.5}
        assert httpx.post(base + "/api/orders", json=ORDER).json()["total"] == 10.25
        assert "TinyShop" in httpx.get(base + "/").text
        assert 'fetch("/api/products")' in httpx.get(base + "/app.js").text


def test_v1_1_only_rewords_the_button(built):
    root, server = run_app(built, "v1.1")
    with server as base:
        assert "Add to cart" in httpx.get(base + "/app.js").text
        assert httpx.post(base + "/api/orders", json=ORDER).json()["total"] == 10.25


def test_v1_2_adds_the_currency_without_breaking_anything(built):
    root, server = run_app(built, "v1.2")
    with server as base:
        order = httpx.post(base + "/api/orders", json=ORDER).json()
        assert order["total"] == 10.25 and order["currency"] == "USD"
        assert httpx.get(base + "/api/products").json()[0]["price"] == 4.5
    assert "CURRENCY=USD" in (root / ".env.example").read_text()


def test_v2_0_backend_bug_ignores_the_quantity(built):
    root, server = run_app(built, "v2.0-backend-bug")
    with server as base:
        assert httpx.post(base + "/api/orders", json=ORDER).json()["total"] == 5.75  # should be 10.25
        assert httpx.post(base + "/api/orders", json={"items": [{"product_id": 1, "quantity": 1}]}).json()["total"] == 4.5
        assert 'fetch("/api/products")' in httpx.get(base + "/app.js").text  # the frontend is fine


def test_v2_1_frontend_bug_calls_a_route_that_does_not_exist(built):
    root, server = run_app(built, "v2.1-frontend-bug")
    with server as base:
        assert 'fetch("/api/product")' in httpx.get(base + "/app.js").text
        assert httpx.get(base + "/api/product").status_code == 404  # what the page asks for
        assert httpx.get(base + "/api/products").status_code == 200  # the backend is fine
        assert httpx.post(base + "/api/orders", json=ORDER).json()["total"] == 10.25


def test_v2_2_contract_break_renames_a_field_the_page_still_reads(built):
    root, server = run_app(built, "v2.2-contract-break")
    with server as base:
        product = httpx.get(base + "/api/products").json()[0]
        assert "unit_price" in product and "price" not in product
        assert "p.price" in httpx.get(base + "/app.js").text  # the page still reads the old name
        assert httpx.post(base + "/api/orders", json=ORDER).json()["total"] == 10.25  # the backend is internally fine


@pytest.mark.parametrize("tag", TAGS)
def test_the_repos_own_tests_pass_on_every_tag(built, tag):
    # The point of the demo: none of the three breaks is caught by the tests the app already has.
    root = checkout(built[0], tag, built[2])
    done = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"], cwd=root,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout[-500:]


# ---------- the live copy: a repo where new commits can arrive while the UI is open ----------

def test_the_live_repo_starts_at_v1_2_with_one_branch(tmp_path):
    shas = shop.build_live(tmp_path / "live")
    assert list(shas) == ["v1.0", "v1.1", "v1.2"]
    branches = subprocess.run(["git", "-C", str(tmp_path / "live"), "branch", "--format=%(refname:short)"], capture_output=True, text=True, check=True).stdout.split()
    assert branches == ["main"]


@pytest.mark.parametrize("change,files", [("backend-bug", ["backend/app.py"]), ("frontend-bug", ["frontend/app.js"]),
                                           ("contract-break", ["backend/app.py", "tests/test_api.py"]), ("safe-copy", ["frontend/app.js"])])
def test_push_commit_adds_the_prepared_change_on_main(tmp_path, change, files):
    live = tmp_path / "live"
    shop.build_live(live)
    sha = shop.push_commit(live, change)
    log = subprocess.run(["git", "-C", str(live), "log", "--format=%H", "-n", "2"], capture_output=True, text=True, check=True).stdout.split()
    assert log[0] == sha and len(log) == 2
    assert sorted(subprocess.run(["git", "-C", str(live), "diff", "--name-only", "HEAD~1", "HEAD"], capture_output=True, text=True, check=True).stdout.split()) == files


def test_push_commit_refuses_unknown_changes_and_a_change_that_does_not_apply(tmp_path):
    live = tmp_path / "live"
    shop.build_live(live)
    with pytest.raises(ValueError, match="unknown change"):
        shop.push_commit(live, "nope")
    shop.push_commit(live, "contract-break")
    with pytest.raises(ValueError, match="does not apply"):
        shop.push_commit(live, "contract-break")  # the file no longer has the text that change replaces
