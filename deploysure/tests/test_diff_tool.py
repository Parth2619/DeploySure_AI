from deploysure.tools.code_reader import release_path
from deploysure.tools.diff_tool import changed_functions, diff_releases, lines_changed

OLD = '''"""mod"""
RATE = 1


def a(x):
    """doc"""
    return x  # note


class K:
    def m(self):
        return 1
'''


def test_comment_and_docstring_edits_are_not_changes():
    new = OLD.replace('"""doc"""', '"""other doc"""').replace("# note", "# changed note")
    assert changed_functions(OLD, new) == []


def test_changed_function_is_named():
    assert changed_functions(OLD, OLD.replace("return x", "return x + 1")) == ["a"]


def test_method_is_named_with_class():
    assert changed_functions(OLD, OLD.replace("return 1", "return 2")) == ["K.m"]


def test_added_function_is_reported():
    assert changed_functions(OLD, OLD + "\n\ndef b():\n    return 0\n") == ["b"]


def test_module_level_constant_change_is_reported():
    assert changed_functions(OLD, OLD.replace("RATE = 1", "RATE = 2")) == ["<module-level>"]


def test_lines_changed_counts_added_and_removed():
    assert lines_changed("a\nb\n", "a\nc\n") == 2


def test_v21_changes_only_notification():
    r = diff_releases(release_path("v2.0"), release_path("v2.1"))
    assert r["changed_files"] == ["notification.py"]
    assert r["details"]["notification.py"]["functions"] == ["order_confirmation"]
    assert r["lines_changed"] == 2


def test_v22_changes_only_payment_refund_amount():
    r = diff_releases(release_path("v2.0"), release_path("v2.2"))
    assert r["changed_files"] == ["payment.py"]
    assert r["details"]["payment.py"]["functions"] == ["refund_amount"]
    assert r["lines_changed"] == 4


def test_identical_releases_have_no_changes():
    assert diff_releases(release_path("v2.0"), release_path("v2.0"))["changed_files"] == []
