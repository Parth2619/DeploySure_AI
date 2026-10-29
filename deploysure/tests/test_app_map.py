from deploysure.tools import app_map


def keys(items):
    return [f"{e['method']} {e['path']}" for e in items]


def test_tinyshop_endpoints_and_fields(tinyshop):
    m = app_map.build_map(tinyshop[0], "v1.2")
    assert keys(m["endpoints"]) == ["GET /api/health", "GET /api/products", "POST /api/orders", "GET /api/orders/{order_id}"]
    by = {f"{e['method']} {e['path']}": e for e in m["endpoints"]}
    assert by["GET /api/products"]["response_fields"] == ["id", "name", "price"]
    assert by["GET /api/products"]["file"] == "backend/app.py"
    assert by["POST /api/orders"]["response_fields"] == ["currency", "id", "total"]
    assert by["POST /api/orders"]["request_fields"] == ["items", "product_id", "quantity"]
    assert by["GET /api/health"]["response_fields"] == ["status"]


def test_tinyshop_frontend_calls(tinyshop):
    m = app_map.build_map(tinyshop[0], "v1.2")
    assert [(c["method"], c["path"], c["file"]) for c in m["frontend_calls"]] == [
        ("GET", "/api/products", "frontend/app.js"), ("POST", "/api/orders", "frontend/app.js")]
    assert m["unmatched_calls"] == []


def test_tinyshop_contract_lists_the_fields_the_page_reads(tinyshop):
    m = app_map.build_map(tinyshop[0], "v1.2")
    by = {c["endpoint"]: c for c in m["contract"]}
    assert by["GET /api/products"]["frontend_reads"] == ["id", "name", "price"]
    assert by["POST /api/orders"]["frontend_reads"] == ["id", "total"]
    assert by["GET /api/products"]["frontend_files"] == ["frontend/app.js"]


def test_tinyshop_stack(tinyshop):
    assert app_map.build_map(tinyshop[0], "v1.2")["stack"] == {"backend": "fastapi", "frontend": "plain html and js"}


def test_a_call_to_a_route_that_does_not_exist_is_unmatched(tinyshop):
    m = app_map.build_map(tinyshop[0], "v2.1-frontend-bug")
    assert [(c["method"], c["path"]) for c in m["unmatched_calls"]] == [("GET", "/api/product")]


def test_renamed_field_is_visible_in_the_endpoint(tinyshop):
    m = app_map.build_map(tinyshop[0], "v2.2-contract-break")
    products = next(e for e in m["endpoints"] if e["path"] == "/api/products")
    assert products["response_fields"] == ["id", "name", "unit_price"]


# ---------- pure functions on text, for shapes the demo app does not use ----------

def test_flask_routes_and_methods():
    source = (
        "from flask import Flask\napp = Flask(__name__)\n\n"
        "@app.route('/ping')\ndef ping():\n    return {'pong': True}\n\n"
        "@app.route('/save/<int:item_id>', methods=['POST', 'PUT'])\ndef save(item_id):\n    return {'saved': item_id}\n")
    found = {f"{e['method']} {e['path']}": e for e in app_map.endpoints_from_python("app.py", source)}
    assert sorted(found) == ["GET /ping", "POST /save/<int:item_id>", "PUT /save/<int:item_id>"]
    assert found["GET /ping"]["response_fields"] == ["pong"]


def test_fastapi_router_and_returned_constant():
    source = ("from fastapi import APIRouter\nrouter = APIRouter()\nITEMS = [{'id': 1, 'title': 'a'}]\n\n"
              "@router.get('/items')\ndef items():\n    return ITEMS\n")
    [endpoint] = app_map.endpoints_from_python("api.py", source)
    assert (endpoint["method"], endpoint["path"], endpoint["response_fields"]) == ("GET", "/items", ["id", "title"])


def test_frontend_call_shapes():
    js = (
        "fetch(`/api/orders/${id}`)\n"
        "axios.post('/api/save', data)\n"
        "fetch('/api/items', { method: 'DELETE' })\n"
        "fetch('https://example.com/api/x?y=1')\n"
        "fetch(someVariable)\n"
        "$.get('/api/old')\n")
    calls = app_map.calls_from_frontend("app.js", js)
    assert [(c["method"], c["path"], c["line"]) for c in calls] == [
        ("GET", "/api/orders/{}", 1), ("POST", "/api/save", 2), ("DELETE", "/api/items", 3),
        ("GET", "/api/x", 4), ("GET", "/api/old", 6)]


def test_path_params_match_any_value():
    assert app_map.paths_match("/api/orders/{}", "/api/orders/{order_id}")
    assert app_map.paths_match("/items/<int:item_id>", "/items/{}")
    assert not app_map.paths_match("/api/product", "/api/products")
    assert not app_map.paths_match("/api/orders/{}/lines", "/api/orders/{order_id}")


def test_node_frontend_and_flask_stack_are_detected():
    files = {"requirements.txt": "flask==3.0\n", "frontend/package.json": '{"dependencies": {"react": "18", "vite": "5"}}',
             "frontend/src/App.jsx": "fetch('/ping')"}
    assert app_map.detect_stack(files) == {"backend": "flask", "frontend": "react"}


def test_sample_bodies_come_from_the_request_model(tinyshop):
    m = app_map.build_map(tinyshop[0], "v1.2")
    order = next(e for e in m["endpoints"] if e["method"] == "POST")
    assert order["sample_bodies"] == [{"items": [{"product_id": 1, "quantity": 1}]}, {"items": [{"product_id": 2, "quantity": 2}]}]
    assert next(e for e in m["endpoints"] if e["path"] == "/api/products")["sample_bodies"] == []


def test_sample_values_follow_the_field_types():
    source = ("from pydantic import BaseModel\nfrom fastapi import FastAPI\napp = FastAPI()\n"
              "class Address(BaseModel):\n    city: str\n    floor: float\n\n"
              "class Person(BaseModel):\n    name: str\n    age: int\n    admin: bool\n    home: Address\n    tags: list[str]\n\n"
              "@app.put('/people')\ndef save(p: Person):\n    return {'ok': True}\n")
    [endpoint] = app_map.endpoints_from_python("a.py", source)
    assert endpoint["sample_bodies"][1] == {"name": "test", "age": 2, "admin": True, "home": {"city": "test", "floor": 2.0}, "tags": ["test"]}


def test_frontend_selectors_are_collected(tinyshop):
    m = app_map.build_map(tinyshop[0], "v1.2")
    assert {"#products", "#cart", "#total", "#place-order", "#result", "#error", ".add"} <= set(m["selectors"])


def test_selectors_from_html_and_js():
    html = '<div id="main" class="card wide"></div>'
    js = 'document.getElementById("save"); el.className = "btn"; el.classList.add("on"); document.querySelectorAll("ul.items li")'
    assert app_map.selectors_from_frontend(html + js) == {"#main", ".card", ".wide", "#save", ".btn", ".on", "ul.items li"}
