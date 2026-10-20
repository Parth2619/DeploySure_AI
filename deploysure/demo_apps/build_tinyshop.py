"""Builds the TinyShop demo repo: a small app with a FastAPI backend and a plain HTML/JS frontend.

Dummy data only. The history is fixed (dates and names are set), so every build gives the same commits:

    v1.0  initial shop                         good
    v1.1  reword the add button, tidy styles   good (frontend only)
    v1.2  report currency from CURRENCY        good (backend and config)
    then three branches, each ONE commit on top of v1.2:
    v2.0-backend-bug     the total ignores quantity           the backend is at fault
    v2.1-frontend-bug    the page calls /api/product (typo)   the frontend is at fault
    v2.2-contract-break  API field price becomes unit_price   the connection is at fault

Usage (from the folder above deploysure/):
    python -m deploysure.demo_apps.build_tinyshop build <folder>              the full history with the three break branches
    python -m deploysure.demo_apps.build_tinyshop live <folder>               only the good history, for the live demo
    python -m deploysure.demo_apps.build_tinyshop push <repo folder> <change>  add a new commit: safe-copy, backend-bug,
                                                                              frontend-bug or contract-break
"""
import os
import subprocess
import sys
from pathlib import Path

REQUIREMENTS = "fastapi==0.143.2\nuvicorn==0.54.0\nhttpx==0.28.1\npytest==9.1.1\n"

README = """# TinyShop

A tiny shop used as a demo target for DeploySure. Dummy data only.

Run it: `uvicorn backend.app:app --port 8000`, then open http://localhost:8000
Test it: `python -m pytest tests -q`
"""

ENV_EXAMPLE = "PORT=8000\n"

BACKEND = r'''"""TinyShop backend. Demo target for DeploySure, dummy data only."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="TinyShop")

PRODUCTS = [
    {"id": 1, "name": "Notebook", "price": 4.5},
    {"id": 2, "name": "Pen", "price": 1.25},
    {"id": 3, "name": "Backpack", "price": 32.0},
]
ORDERS: dict[int, dict] = {}


class OrderItem(BaseModel):
    product_id: int
    quantity: int


class OrderIn(BaseModel):
    items: list[OrderItem]


def order_total(items: list[OrderItem]) -> float:
    prices = {p["id"]: p["price"] for p in PRODUCTS}
    return round(sum(prices[i.product_id] * i.quantity for i in items), 2)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/products")
def products() -> list[dict]:
    return PRODUCTS


@app.post("/api/orders")
def create_order(order: OrderIn) -> dict:
    if not order.items:
        raise HTTPException(status_code=400, detail="order needs at least one item")
    known = {p["id"] for p in PRODUCTS}
    if any(i.product_id not in known or i.quantity < 1 for i in order.items):
        raise HTTPException(status_code=400, detail="unknown product or bad quantity")
    order_id = len(ORDERS) + 1
    ORDERS[order_id] = {"id": order_id, "total": order_total(order.items)}
    return ORDERS[order_id]


@app.get("/api/orders/{order_id}")
def get_order(order_id: int) -> dict:
    if order_id not in ORDERS:
        raise HTTPException(status_code=404, detail="no such order")
    return ORDERS[order_id]


# Mounted last so the API routes above win.
app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[1] / "frontend", html=True), name="frontend")
'''

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>TinyShop</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <h1>TinyShop</h1>
  <p id="error" role="alert"></p>
  <ul id="products"></ul>
  <h2>Your cart</h2>
  <ul id="cart"></ul>
  <p>Total: <span id="total">$0.00</span></p>
  <button id="place-order" disabled>Place order</button>
  <p id="result"></p>
  <script src="app.js"></script>
</body>
</html>
"""

STYLE_CSS = """body { font-family: sans-serif; margin: 2rem; }
#error { color: #b00020; }
li { margin: 0.25rem 0; }
"""

APP_JS = r"""const cart = {};   // product id -> quantity
let products = [];

function money(n) { return "$" + Number(n).toFixed(2); }

function render() {
  const list = document.getElementById("cart");
  list.replaceChildren();
  let total = 0;
  for (const p of products) {
    const q = cart[p.id] || 0;
    if (!q) continue;
    total += p.price * q;
    const li = document.createElement("li");
    li.textContent = `${p.name} x ${q}`;
    list.append(li);
  }
  document.getElementById("total").textContent = money(total);
  document.getElementById("place-order").disabled = total === 0;
}

async function loadProducts() {
  try {
    const res = await fetch("/api/products");
    if (!res.ok) throw new Error("status " + res.status);
    products = await res.json();
  } catch (err) {
    document.getElementById("error").textContent = "Could not load products";
    return;
  }
  const ul = document.getElementById("products");
  for (const p of products) {
    const li = document.createElement("li");
    li.textContent = `${p.name} ${money(p.price)} `;
    const button = document.createElement("button");
    button.className = "add";
    button.textContent = "Add";
    button.addEventListener("click", () => { cart[p.id] = (cart[p.id] || 0) + 1; render(); });
    li.append(button);
    ul.append(li);
  }
}

async function placeOrder() {
  const items = Object.entries(cart).map(([id, quantity]) => ({ product_id: Number(id), quantity }));
  const res = await fetch("/api/orders", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items }) });
  const out = document.getElementById("result");
  if (!res.ok) { out.textContent = "Order failed"; return; }
  const order = await res.json();
  out.textContent = `Order #${order.id} total ${money(order.total)}`;
}

document.getElementById("place-order").addEventListener("click", placeOrder);
loadProducts();
"""

TESTS = r'''from fastapi.testclient import TestClient

from backend.app import app

client = TestClient(app)


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_products_have_prices():
    data = client.get("/api/products").json()
    assert len(data) == 3 and all(p["price"] > 0 for p in data)


def test_order_total_for_one_item():
    r = client.post("/api/orders", json={"items": [{"product_id": 1, "quantity": 1}]})
    assert r.json()["total"] == 4.5


def test_empty_order_is_rejected():
    assert client.post("/api/orders", json={"items": []}).status_code == 400
'''


def base_files() -> dict[str, str]:
    return {
        "README.md": README, "requirements.txt": REQUIREMENTS, ".env.example": ENV_EXAMPLE,
        "backend/__init__.py": "", "backend/app.py": BACKEND,
        "frontend/index.html": INDEX_HTML, "frontend/style.css": STYLE_CSS, "frontend/app.js": APP_JS,
        "tests/test_api.py": TESTS,
    }


def swap(files: dict[str, str], name: str, old: str, new: str) -> dict[str, str]:
    """A copy of files where one text in one file is replaced. The old text must exist."""
    assert old in files[name], f"{old!r} not found in {name}"
    return {**files, name: files[name].replace(old, new)}


def v1_1(files):  # frontend only: friendlier button, tidier list
    files = swap(files, "frontend/app.js", 'button.textContent = "Add";', 'button.textContent = "Add to cart";')
    return swap(files, "frontend/style.css", "li { margin: 0.25rem 0; }", "li { margin: 0.5rem 0; }\nbutton { cursor: pointer; }")


def v1_2(files):  # backend and config: report the currency
    files = swap(files, "backend/app.py", "from pathlib import Path\n", "import os\nfrom pathlib import Path\n")
    files = swap(files, "backend/app.py", 'ORDERS[order_id] = {"id": order_id, "total": order_total(order.items)}',
                 'ORDERS[order_id] = {"id": order_id, "total": order_total(order.items), "currency": os.getenv("CURRENCY", "USD")}')
    return swap(files, ".env.example", "PORT=8000\n", "PORT=8000\nCURRENCY=USD\n")


def backend_bug(files):  # the total forgets the quantity
    return swap(files, "backend/app.py", "prices[i.product_id] * i.quantity for i in items", "prices[i.product_id] for i in items")


def frontend_bug(files):  # typo in the route the page calls
    return swap(files, "frontend/app.js", 'fetch("/api/products")', 'fetch("/api/product")')


def contract_break(files):  # the API renames a field, the page still reads the old name
    files = swap(files, "backend/app.py", '"price": 4.5', '"unit_price": 4.5')
    files = swap(files, "backend/app.py", '"price": 1.25', '"unit_price": 1.25')
    files = swap(files, "backend/app.py", '"price": 32.0', '"unit_price": 32.0')
    files = swap(files, "backend/app.py", 'prices = {p["id"]: p["price"] for p in PRODUCTS}', 'prices = {p["id"]: p["unit_price"] for p in PRODUCTS}')
    return swap(files, "tests/test_api.py", 'p["price"] > 0', 'p["unit_price"] > 0')  # the backend's own tests are updated


def git(repo: Path, *args: str, date: str | None = None) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "TinyShop Dev", "GIT_AUTHOR_EMAIL": "dev@tinyshop.example",
           "GIT_COMMITTER_NAME": "TinyShop Dev", "GIT_COMMITTER_EMAIL": "dev@tinyshop.example"}
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def write(repo: Path, files: dict[str, str]) -> None:
    for old in list(repo.rglob("*")):  # drop files that a commit removes, keep .git
        if old.is_file() and ".git" not in old.relative_to(repo).parts and old.relative_to(repo).as_posix() not in files:
            old.unlink()
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")


def commit(repo: Path, files: dict[str, str], message: str, tag: str, day: int) -> None:
    write(repo, files)
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message, date=f"2026-10-{day:02d}T10:00:00+00:00")
    git(repo, "tag", tag)


def build(dest: Path) -> dict[str, str]:
    """Creates the repo at dest (must not exist) and returns {tag: commit sha}."""
    dest.mkdir(parents=True)
    git(dest, "init", "-b", "main")
    git(dest, "config", "core.autocrlf", "false")  # checkouts must be exactly what was committed
    good = base_files()
    commit(dest, good, "Initial TinyShop: product list, cart and orders", "v1.0", 1)
    good = v1_1(good)
    commit(dest, good, "Reword the add button and tidy the list", "v1.1", 2)
    good = v1_2(good)
    commit(dest, good, "Report the currency from the CURRENCY setting", "v1.2", 3)
    for branch, change, message, tag, day in [
        ("backend-bug", backend_bug, "Simplify the order total calculation", "v2.0-backend-bug", 4),
        ("frontend-bug", frontend_bug, "Load products from the shorter products route", "v2.1-frontend-bug", 4),
        ("contract-break", contract_break, "Rename price to unit_price in the API", "v2.2-contract-break", 4),
    ]:
        git(dest, "checkout", "-b", branch, "v1.2")
        commit(dest, change(good), message, tag, day)
    git(dest, "checkout", "main")
    write(dest, good)
    return {t: git(dest, "rev-parse", t) for t in git(dest, "tag", "--list").split()}


def build_live(dest: Path) -> dict[str, str]:
    """A repo with only the good history (v1.0 to v1.2 on main). New commits can then arrive with push_commit."""
    dest.mkdir(parents=True)
    git(dest, "init", "-b", "main")
    git(dest, "config", "core.autocrlf", "false")
    good = base_files()
    commit(dest, good, "Initial TinyShop: product list, cart and orders", "v1.0", 1)
    good = v1_1(good)
    commit(dest, good, "Reword the add button and tidy the list", "v1.1", 2)
    commit(dest, v1_2(good), "Report the currency from the CURRENCY setting", "v1.2", 3)
    return {t: git(dest, "rev-parse", t) for t in git(dest, "tag", "--list").split()}


def safe_copy(files):  # frontend only: a reworded button, harmless
    return swap(files, "frontend/app.js", 'button.textContent = "Add to cart";', 'button.textContent = "Add to basket";')


LIVE_CHANGES = {
    "safe-copy": (safe_copy, "Reword the add button again"),
    "backend-bug": (backend_bug, "Simplify the order total calculation"),
    "frontend-bug": (frontend_bug, "Load products from the shorter products route"),
    "contract-break": (contract_break, "Rename price to unit_price in the API"),
}


def push_commit(repo: Path, change: str) -> str:
    """Adds one prepared change as a new commit on the current branch, like a developer would. Returns the new sha."""
    if change not in LIVE_CHANGES:
        raise ValueError(f"unknown change {change!r}. Choose one of: {', '.join(LIVE_CHANGES)}")
    apply, message = LIVE_CHANGES[change]
    tracked = git(repo, "ls-files").split("\n")
    files = {name: (repo / name).read_text(encoding="utf-8") for name in tracked if name}
    try:
        files = apply(files)
    except AssertionError:
        raise ValueError(f"the change {change!r} does not apply: the code it edits is not there any more")
    write(repo, files)
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


if __name__ == "__main__":
    usage = "usage: build <folder> | live <folder> | push <repo folder> <change>"
    command, rest = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 and sys.argv[1] in {"build", "live", "push"} else ("build", sys.argv[1:])
    try:
        if command == "push" and len(rest) == 2:
            print(f"committed {push_commit(Path(rest[0]), rest[1])[:10]}: {LIVE_CHANGES[rest[1]][1]}")
        elif command in {"build", "live"} and len(rest) == 1:
            for tag, sha in (build if command == "build" else build_live)(Path(rest[0])).items():
                print(f"{tag:<20} {sha[:10]}")
        else:
            sys.exit(usage)
    except ValueError as err:
        sys.exit(str(err))
