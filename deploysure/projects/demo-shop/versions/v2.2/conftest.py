# Writes a critical flag into the junit XML so the runner reads status and criticality in one run.
def pytest_collection_modifyitems(items):
    for item in items:
        flag = item.get_closest_marker("critical") is not None
        item.user_properties.append(("critical", str(flag)))
