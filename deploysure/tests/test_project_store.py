import pytest

from deploysure.tools import code_reader, project_store as ps
from deploysure.tools.project_store import ProjectError


@pytest.fixture
def store(tmp_path, monkeypatch):
    """An empty projects folder, so tests never touch the real demo shop."""
    monkeypatch.setattr(code_reader, "PROJECTS_ROOT", tmp_path / "projects")
    return tmp_path


def make_src(base, name="src", code="def add(a, b):\n    return a + b\n"):
    folder = base / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "shop.py").write_text(code)
    (folder / "test_shop.py").write_text("import shop\n\ndef test_add():\n    assert shop.add(1, 2) == 3\n")
    return folder


def test_slugify():
    assert ps.slugify("My Shop!") == "my-shop"
    assert len(ps.slugify("x" * 60)) == 40
    with pytest.raises(ProjectError) as err:
        ps.slugify("!!!")
    assert err.value.status == 400


def test_create_project_copies_and_writes_defaults(store):
    card = ps.create_project("My Shop", str(make_src(store)))
    assert card["latest_version"] == "v1.0"
    folder = code_reader.release_path("v1.0", "my-shop")
    assert (folder / "shop.py").is_file() and (folder / "pytest.ini").is_file() and (folder / "conftest.py").is_file()
    assert ps.list_versions("my-shop")[0]["baseline"] is None


def test_duplicate_project_is_409(store):
    src = make_src(store)
    ps.create_project("Shop", str(src))
    with pytest.raises(ProjectError) as err:
        ps.create_project("Shop", str(src))
    assert err.value.status == 409


def test_same_slug_collision_is_409(store):
    src = make_src(store)
    ps.create_project("Shop!", str(src))
    with pytest.raises(ProjectError) as err:
        ps.create_project("shop", str(src))
    assert err.value.status == 409


def test_bad_folder_paths_are_400_and_create_nothing(store):
    only_tests = store / "only_tests"
    only_tests.mkdir()
    (only_tests / "test_x.py").write_text("")
    a_file = store / "file.txt"
    a_file.write_text("x")
    for bad in (store / "missing", a_file, only_tests):
        with pytest.raises(ProjectError) as err:
            ps.create_project("Bad", str(bad))
        assert err.value.status == 400
    assert ps.list_projects() == []


def test_folder_path_with_spaces_works(store):
    card = ps.create_project("Spaced", str(make_src(store, name="my folder")))
    assert card["version_count"] == 1


def test_copy_limits(store):
    many = make_src(store, "many")
    for i in range(201):
        (many / f"m{i}.py").write_text("")
    big = make_src(store, "big")
    (big / "huge.py").write_text("#" * (300 * 1024))
    odd = make_src(store, "odd")
    (odd / "__pycache__").mkdir()
    (odd / "__pycache__" / "x.py").write_text("")
    (odd / "notes.txt").write_text("hi")
    for src in (many, big):
        with pytest.raises(ProjectError) as err:
            ps.create_project("Limit " + src.name, str(src))
        assert err.value.status == 400
    ps.create_project("Odd", str(odd))
    copied = {p.name for p in code_reader.release_path("v1.0", "odd").iterdir()}
    assert "notes.txt" not in copied and "__pycache__" not in copied


def test_add_version_baseline_is_previous(store):
    ps.create_project("Shop", str(make_src(store)))
    ps.add_version("shop", "v2", str(make_src(store, "s2")), "second")
    ps.add_version("shop", "v3", str(make_src(store, "s3")), "third")
    baselines = {v["version"]: v["baseline"] for v in ps.list_versions("shop")}
    assert baselines == {"v1.0": None, "v2": "v1.0", "v3": "v2"}


def test_bad_version_names_and_conflicts(store):
    ps.create_project("Shop", str(make_src(store)))
    src = str(make_src(store, "s2"))
    for bad in ("..", "a/b", "", "x" * 31):
        with pytest.raises(ProjectError) as err:
            ps.add_version("shop", bad, src, "")
        assert err.value.status == 400
    with pytest.raises(ProjectError) as err:
        ps.add_version("shop", "v1.0", src, "")
    assert err.value.status == 409
    with pytest.raises(ProjectError) as err:
        ps.add_version("nope", "v2", src, "")
    assert err.value.status == 404


def test_title_is_first_note_line(store):
    ps.create_project("Shop", str(make_src(store)))
    v = ps.add_version("shop", "v2", str(make_src(store, "s2")), "Fix refunds\nMore detail here")
    assert v["title"] == "Fix refunds"
    assert ps.add_version("shop", "v3", str(make_src(store, "s3")), "")["title"] == "v3"


def test_modules_exclude_tests(store):
    ps.create_project("Shop", str(make_src(store)))
    assert ps.project_modules("shop") == ["shop"]


def test_critical_modules_are_saved(store):
    ps.create_project("Shop", str(make_src(store)), critical_modules=["shop"])
    assert ps.load_project("shop")["critical_modules"] == ["shop"]


def test_card_has_last_result_after_save(store):
    ps.create_project("Shop", str(make_src(store)))
    assert ps.list_projects()[0]["last_result"] is None
    ps.save_result("shop", "v1.0", {"decision": "DEPLOY", "risk_score": 12, "risk_level": "LOW", "retry_count": 0})
    card = ps.list_projects()[0]
    assert card["last_result"]["decision"] == "DEPLOY" and card["last_result"]["risk_score"] == 12


def test_get_project_has_versions_and_modules(store):
    ps.create_project("Shop", str(make_src(store)))
    got = ps.get_project("shop")
    assert got["name"] == "Shop" and len(got["versions"]) == 1 and got["modules"] == ["shop"]


def test_damaged_project_file_does_not_hide_other_projects(store):
    ps.create_project("Good", str(make_src(store, "g")))
    ps.create_project("Bad", str(make_src(store, "b")))
    (code_reader.project_path("bad") / "project.json").write_text("{ not json")
    cards = {c["id"]: c for c in ps.list_projects()}
    assert set(cards) == {"good", "bad"} and "project.json" in cards["bad"]["error"] and "error" not in cards["good"]
    with pytest.raises(ProjectError) as err:
        ps.get_project("bad")
    assert "project.json" in str(err.value)


def test_version_file_missing_a_field_is_a_clear_error(store):
    ps.create_project("Shop", str(make_src(store)))
    path = code_reader.release_path("v1.0", "shop") / "version.json"
    path.write_text('{"version": "v1.0"}')
    with pytest.raises(ProjectError) as err:
        ps.list_versions("shop")
    assert "version.json" in str(err.value)


def test_failed_copy_leaves_nothing_behind(store, monkeypatch):
    import shutil
    real, calls = shutil.copy2, []

    def flaky(src, dst, **kw):
        calls.append(src)
        if len(calls) == 2:
            raise OSError("locked")
        return real(src, dst, **kw)

    monkeypatch.setattr(shutil, "copy2", flaky)
    with pytest.raises(ProjectError):
        ps.create_project("Shop", str(make_src(store)))
    assert not code_reader.project_path("shop").exists()
    calls.clear()
    monkeypatch.setattr(shutil, "copy2", real)
    ps.create_project("Shop", str(make_src(store)))
    monkeypatch.setattr(shutil, "copy2", flaky)
    with pytest.raises(ProjectError):
        ps.add_version("shop", "v2", str(make_src(store, "s2")), "")
    monkeypatch.setattr(shutil, "copy2", real)
    ps.add_version("shop", "v2", str(make_src(store, "s3")), "")


def test_protected_project_rejects_new_versions(store):
    import json
    ps.create_project("Shop", str(make_src(store)))
    path = code_reader.project_path("shop") / "project.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "protected": True}))
    with pytest.raises(ProjectError) as err:
        ps.add_version("shop", "v2", str(make_src(store, "s2")), "")
    assert err.value.status == 403


@pytest.mark.parametrize("bad", ["v1.", "NUL", "con", "Com1", "nul.txt", "aux"])
def test_windows_unsafe_version_names_are_400(store, bad):
    with pytest.raises(ProjectError) as err:
        ps.check_version_name(bad)
    assert err.value.status == 400


def test_version_names_differing_only_in_case_conflict(store):
    ps.create_project("Shop", str(make_src(store)))
    ps.add_version("shop", "v2", str(make_src(store, "s2")), "")
    with pytest.raises(ProjectError) as err:
        ps.add_version("shop", "V2", str(make_src(store, "s3")), "")
    assert err.value.status == 409


def test_quoted_folder_path_is_accepted(store):
    src = make_src(store, "my folder")
    assert ps.create_project("Quoted", f'"{src}"')["version_count"] == 1


def test_oversized_text_is_rejected(store):
    src = str(make_src(store))
    with pytest.raises(ProjectError):
        ps.create_project("x" * 81, src)
    ps.create_project("Shop", src)
    with pytest.raises(ProjectError):
        ps.add_version("shop", "v2", str(make_src(store, "s2")), "n" * 5001)


def test_result_is_stale_after_test_cases_change(store):
    import time
    from deploysure.tools import test_cases as tc
    ps.create_project("Shop", str(make_src(store)))
    ps.save_result("shop", "v1.0", {"decision": "DEPLOY", "risk_score": 1, "risk_level": "LOW", "retry_count": 0})
    assert ps.list_versions("shop")[0]["last_result"]["stale"] is False
    time.sleep(0.05)
    tc.add_test_case("shop", "t", "import shop\n\n\ndef test_t():\n    assert shop.add(1, 2) == 3\n", False)
    assert ps.list_versions("shop")[0]["last_result"]["stale"] is True
