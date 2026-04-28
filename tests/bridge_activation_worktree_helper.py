import json
import time


PREVIOUS_ACTIVATION_QUESTION = "Does she ever use her tongue to clean her paws or her face?"
PIVOT_CHILD_REPLY = "No, but she like to bury the food"
PAWS_COVER_QUESTION = (
    "That is funny that she tries to bury it! "
    "Does she use her paws to push at the floor around the bowl like she is trying to cover it up?"
)
SUCCESS_CHILD_REPLY = "yep"
ANCHOR_GENERAL_RESPONSE = (
    "She does use her paws to cover the food! "
    "Cats have soft paw pads that help them move quietly."
)


def parse_sse(response_data):
    events = []
    text = response_data.decode("utf-8")
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        event_type = None
        data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_type = line[7:].strip()
            elif line.startswith("data: "):
                data = json.loads(line[6:].strip())
        if event_type:
            events.append({"event": event_type, "data": data})
    return events


def final_chunk_from_response(response):
    return [event["data"] for event in parse_sse(response.data) if event["event"] == "chunk"][-1]


def seed_bridge_activation_session(session_id: str = "worktree-bridge-activation"):
    import paixueji_app

    assistant = paixueji_app.PaixuejiAssistant(client=object())
    assistant.age = 6
    assistant.object_name = "cat food"
    assistant.surface_object_name = "cat food"
    assistant.anchor_object_name = "cat"
    assistant.anchor_status = "anchored_high"
    assistant.anchor_relation = "food_for"
    assistant.anchor_confidence_band = "high"
    assistant.begin_bridge_activation(
        anchor_name="cat",
        physical_dimensions={"appearance": {"paw_pads": "Soft pads underneath the paws"}},
        engagement_dimensions={},
        grounding_context=(
            "Current-object KB for cat:\n"
            "[physical.appearance]\n"
            "  - paw pads: Soft pads underneath the paws"
        ),
    )
    assistant.activation_last_question = PREVIOUS_ACTIVATION_QUESTION
    assistant.activation_handoff_ready = True
    assistant.conversation_history = [
        {"role": "system", "content": "System prompt placeholder."},
        {
            "role": "assistant",
            "content": PREVIOUS_ACTIVATION_QUESTION,
            "mode": "chat",
            "response_type": "bridge_activation",
        },
    ]
    paixueji_app.sessions[session_id] = assistant
    return assistant


def make_bridge_activation_generator(response_text: str = PAWS_COVER_QUESTION):
    async def fake_generator(*args, **kwargs):
        yield (response_text, None, response_text)
        yield ("", None, response_text)

    return fake_generator


def make_anchor_general_stream(response_text: str = ANCHOR_GENERAL_RESPONSE):
    from schema import StreamChunk

    async def fake_graph_execution(initial_state):
        yield StreamChunk(
            response=response_text,
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
            activation_turn_count=0,
            activation_handoff_ready=False,
        )

    return fake_graph_execution


def fetch_exchanges_payload(client, session_id: str):
    response = client.get(f"/api/exchanges/{session_id}")
    assert response.status_code == 200
    return response.get_json()
