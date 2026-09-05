"""Each detector must fire on its fault and stay quiet on a clean stream."""

from clinical_agent.detectors import (
    DetectorConfig,
    cross_patient_attempt,
    latency_cliff,
    refusal_rate_drift,
    run_detectors,
    tool_error_rate_spike,
)

CFG = DetectorConfig(window=50)


def rec(**over):
    base = dict(session_id="s1", total_ms=10.0, tool_called=True,
                tool_error=False, refused=False, scope_violation=False)
    base.update(over)
    return base


def clean(n=400):
    return [rec(session_id=f"s{i}", refused=(i % 4 == 0)) for i in range(n)]


def test_clean_stream_is_quiet():
    assert run_detectors(clean(), CFG) == {}


def test_refusal_rate_drift_fires_when_the_guardrail_goes_quiet():
    stream = clean(400)
    for record in stream[-50:]:
        record["refused"] = False
    assert refusal_rate_drift(stream, CFG) is not None


def test_refusal_rate_drift_quiet_when_rate_holds():
    assert refusal_rate_drift(clean(400), CFG) is None


def test_tool_error_rate_spike():
    stream = clean(400)
    for record in stream[:100]:
        record["tool_error"] = True
    assert tool_error_rate_spike(stream, CFG) is not None
    assert tool_error_rate_spike(clean(400), CFG) is None


def test_latency_cliff_compares_like_with_like():
    """The reference is the opening window's p95, not its median: a queueing tail alone
    must not look like a cliff."""
    stream = clean(400)
    for record in stream[-50:]:
        record["total_ms"] = 900.0
    assert latency_cliff(stream, CFG) is not None

    noisy = clean(400)
    for index, record in enumerate(noisy):
        record["total_ms"] = 200.0 if index % 20 == 0 else 10.0
    assert latency_cliff(noisy, CFG) is None, "a fat tail throughout is not a cliff"


def test_latency_cliff_is_not_hidden_by_a_long_running_fault():
    """A fault covering most of the run must still be caught: the reference is the
    earliest window, so a contaminated trailing baseline cannot mask it."""
    stream = clean(400)
    for record in stream[100:]:
        record["total_ms"] = 900.0
    assert latency_cliff(stream, CFG) is not None


def test_cross_patient_attempt_fires_on_a_single_event():
    stream = clean(400)
    stream[7]["scope_violation"] = True
    alert = cross_patient_attempt(stream, CFG)
    assert alert is not None and "s7" in alert
    assert cross_patient_attempt(clean(400), CFG) is None


def test_short_streams_do_not_alarm():
    assert refusal_rate_drift(clean(10), CFG) is None
    assert latency_cliff(clean(10), CFG) is None
