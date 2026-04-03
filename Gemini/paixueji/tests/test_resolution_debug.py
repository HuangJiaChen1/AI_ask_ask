from resolution_debug import build_resolution_debug, format_resolution_log_line


def test_build_resolution_debug_includes_core_fields():
    debug = build_resolution_debug(
        surface_object_name="cat food",
        decision_source="relation_repair",
        decision_reason="primary_low_confidence_single_candidate",
        candidate_anchors=["cat"],
        model_attempted=True,
        raw_model_response='{"anchor_object_name": null}',
        parsed_anchor_raw=None,
        parsed_relation_raw=None,
        parsed_confidence_raw="low",
        anchor_object_name="cat",
        anchor_status="anchored_high",
    )

    assert debug["surface_object_name"] == "cat food"
    assert debug["decision_source"] == "relation_repair"
    assert debug["candidate_anchors"] == ["cat"]
    assert debug["model_attempted"] is True
    assert debug["anchor_status"] == "anchored_high"


def test_format_resolution_log_line_contains_reason_and_candidates():
    line = format_resolution_log_line(
        session_id="abc",
        request_id="req",
        resolution_debug={
            "decision_source": "candidate_fallback",
            "decision_reason": "relation_repair_failed",
            "candidate_anchors": ["cat"],
            "anchor_status": "anchored_medium",
        },
    )

    assert "session=abc" in line
    assert "request=req" in line
    assert "decision_source=candidate_fallback" in line
    assert "decision_reason=relation_repair_failed" in line
