from langgraph.graph import END

from deploysure.orchestration.routing import MAX_RETRIES, route_after_critic


def test_pass_ends():
    assert route_after_critic({"critic_result": "PASS", "retry_count": 0}) == END


def test_pass_ends_even_after_retries():
    assert route_after_critic({"critic_result": "PASS", "retry_count": MAX_RETRIES}) == END


def test_fail_under_cap_replans():
    assert route_after_critic({"critic_result": "FAIL", "retry_count": 0}) == "replan"
    assert route_after_critic({"critic_result": "FAIL", "retry_count": MAX_RETRIES - 1}) == "replan"


def test_fail_at_cap_goes_to_manual_review():
    assert route_after_critic({"critic_result": "FAIL", "retry_count": MAX_RETRIES}) == "manual_review"


def test_cap_is_two():
    assert MAX_RETRIES == 2
