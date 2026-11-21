from simulator.retail_onboarding import run_retail_onboarding


def test_synthetic_retail_onboarding_reports_application_to_approval_time() -> None:
    results = run_retail_onboarding()
    assert all(result.synthetic for result in results)
    assert tuple(result.scenario for result in results) == (
        "CLEAN",
        "UNABLE_TO_VERIFY",
        "LIST_MATCH_ESCALATION",
        "PROFILE_INCOMPLETE",
    )
    assert results[0].application_to_approval_seconds == 30
    assert results[0].refusal is None
    assert tuple(result.refusal for result in results[1:]) == (
        "CIP_UNABLE_TO_VERIFY",
        "CIP_LIST_MATCH_ESCALATE",
        "PROFILE_INCOMPLETE",
    )
    assert all(result.application_to_approval_seconds is None for result in results[1:])
