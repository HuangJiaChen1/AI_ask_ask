import time

from tests.bridge_activation_worktree_helper import (
    ANCHOR_GENERAL_RESPONSE,
    PAWS_COVER_QUESTION,
    PIVOT_CHILD_REPLY,
    SUCCESS_CHILD_REPLY,
    fetch_exchanges_payload,
    final_chunk_from_response,
    make_anchor_general_stream,
    make_bridge_activation_generator,
    seed_bridge_activation_session,
)


def test_seeded_bridge_activation_pivot_then_success_commits_and_is_visible_in_transcript(client, monkeypatch):
    session_id = "worktree-e2e"
    seed_bridge_activation_session(session_id)

    monkeypatch.setattr(
        "paixueji_app.generate_bridge_activation_response_stream",
        make_bridge_activation_generator(),
    )
    monkeypatch.setattr(
        "paixueji_app.stream_graph_execution",
        make_anchor_general_stream(),
    )

    pivot_response = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": PIVOT_CHILD_REPLY},
    )
    pivot_chunk = final_chunk_from_response(pivot_response)

    assert pivot_chunk["response_type"] == "bridge_activation"
    assert pivot_chunk["bridge_phase"] == "activation"
    assert pivot_chunk["current_object_name"] == "cat food"
    assert pivot_chunk["response"] == PAWS_COVER_QUESTION
    assert pivot_chunk["bridge_debug"]["activation_transition"]["question_validation"]["handoff_ready_question"] is True
    assert pivot_chunk["bridge_debug"]["activation_transition"]["answer_validation"]["answered_previous_question"] is False
    assert pivot_chunk["bridge_debug"]["activation_transition"]["outcome"]["bridge_success"] is False

    success_response = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": SUCCESS_CHILD_REPLY},
    )
    success_chunk = final_chunk_from_response(success_response)

    assert success_chunk["response_type"] == "correct_answer"
    assert success_chunk["bridge_phase"] == "anchor_general"
    assert success_chunk["current_object_name"] == "cat"
    assert success_chunk["learning_anchor_active"] is True
    assert success_chunk["response"] == ANCHOR_GENERAL_RESPONSE
    assert success_chunk["bridge_debug"]["activation_transition"]["outcome"]["handoff_result"] == "committed_to_anchor_general"
    assert success_chunk["bridge_debug"]["activation_transition"]["outcome"]["bridge_success"] is True

    transcript = fetch_exchanges_payload(client, session_id)
    assert transcript["introduction"]["response_type"] == "bridge_activation"
    assert transcript["introduction"]["content"].endswith("paws or her face?")
    assert len(transcript["exchanges"]) == 2

    first_exchange, second_exchange = transcript["exchanges"]

    assert first_exchange["child_response"] == PIVOT_CHILD_REPLY
    assert first_exchange["model_response"] == PAWS_COVER_QUESTION
    assert first_exchange["response_type"] == "bridge_activation"
    assert first_exchange["bridge_debug"]["activation_transition"]["question_validation"]["handoff_ready_question"] is True
    assert first_exchange["bridge_debug"]["activation_transition"]["answer_validation"]["answered_previous_question"] is False
    assert first_exchange["bridge_debug"]["activation_transition"]["outcome"]["bridge_success"] is False

    assert second_exchange["child_response"] == SUCCESS_CHILD_REPLY
    assert second_exchange["model_response"] == ANCHOR_GENERAL_RESPONSE
    assert second_exchange["response_type"] == "correct_answer"
    assert second_exchange["bridge_debug"]["activation_transition"]["outcome"]["handoff_result"] == "committed_to_anchor_general"
    assert second_exchange["bridge_debug"]["activation_transition"]["outcome"]["bridge_success"] is True


def test_bridge_handoff_correct_answer_persists_open_ended_question_style(client, monkeypatch):
    from schema import StreamChunk

    session_id = "handoff-open-ended-style"
    seed_bridge_activation_session(session_id)

    async def fake_graph_execution(initial_state):
        yield StreamChunk(
            response=(
                "It sounds like she finds a cozy spot to settle down after her meal. "
                "What does she do when she wakes up from her nap?"
            ),
            session_finished=False,
            duration=0.0,
            token_usage=None,
            finish=True,
            sequence_number=1,
            timestamp=time.time(),
            session_id=initial_state["session_id"],
            request_id=initial_state["request_id"],
            response_type="correct_answer",
            current_object_name="cat",
            surface_object_name="cat food",
            anchor_object_name="cat",
            learning_anchor_active=True,
            bridge_phase="anchor_general",
            question_style="open_ended",
        )

    monkeypatch.setattr("paixueji_app.stream_graph_execution", fake_graph_execution)

    response = client.post(
        "/api/continue",
        json={"session_id": session_id, "child_input": SUCCESS_CHILD_REPLY},
    )
    final_chunk = final_chunk_from_response(response)

    assert final_chunk["question_style"] == "open_ended"

    import paixueji_app

    saved_turn = paixueji_app.sessions[session_id].conversation_history[-1]
    assert saved_turn["response_type"] == "correct_answer"
    assert saved_turn["question_style"] == "open_ended"
