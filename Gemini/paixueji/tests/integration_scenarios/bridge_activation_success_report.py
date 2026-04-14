#!/usr/bin/env python3

import os
import sys
from unittest.mock import patch

# Ensure project root and pytest dependency stubs are available when run directly.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

import tests.conftest  # noqa: F401

import paixueji_app
from tests.bridge_activation_worktree_helper import (
    PIVOT_CHILD_REPLY,
    SUCCESS_CHILD_REPLY,
    fetch_exchanges_payload,
    final_chunk_from_response,
    make_anchor_general_stream,
    make_bridge_activation_generator,
    seed_bridge_activation_session,
)


def main():
    paixueji_app.app.config["TESTING"] = True
    paixueji_app.sessions = {}
    session_id = "bridge-activation-report"

    with patch(
        "paixueji_app.generate_bridge_activation_response_stream",
        make_bridge_activation_generator(),
    ), patch(
        "paixueji_app.stream_graph_execution",
        make_anchor_general_stream(),
    ):
        seed_bridge_activation_session(session_id)

        with paixueji_app.app.test_client() as client:
            pivot_chunk = final_chunk_from_response(
                client.post(
                    "/api/continue",
                    json={"session_id": session_id, "child_input": PIVOT_CHILD_REPLY},
                )
            )
            success_chunk = final_chunk_from_response(
                client.post(
                    "/api/continue",
                    json={"session_id": session_id, "child_input": SUCCESS_CHILD_REPLY},
                )
            )
            transcript = fetch_exchanges_payload(client, session_id)

    first_exchange, second_exchange = transcript["exchanges"]

    print("# BridgeActivation Worktree Report\n")
    print("## Scenario Setup")
    print("- Surface object: `cat food`")
    print("- Anchor object: `cat`")
    print("- Seeded state: `bridge_phase=activation`, previous question already asked\n")

    print("## Exchange 1")
    print(f"- Previous question: `{transcript['introduction']['content']}`")
    print(f"- Child reply: `{first_exchange['child_response']}`")
    print(f"- Model reply: `{first_exchange['model_response']}`")
    print(
        "- Outcome: stayed in `bridge_activation` because the reply pivoted instead of answering "
        "the previous question directly"
    )
    print(
        "- Signals: "
        f"`handoff_ready_question={first_exchange['bridge_debug']['activation_transition']['question_validation']['handoff_ready_question']}`, "
        f"`answered_previous_question={first_exchange['bridge_debug']['activation_transition']['answer_validation']['answered_previous_question']}`, "
        f"`bridge_success={first_exchange['bridge_debug']['activation_transition']['outcome']['bridge_success']}`\n"
    )

    print("## Exchange 2")
    print(f"- Child reply: `{second_exchange['child_response']}`")
    print(f"- Model reply: `{second_exchange['model_response']}`")
    print("- Outcome: committed handoff into anchor chat because `yep` directly answered the paws-cover question")
    print(
        "- Signals: "
        f"`handoff_result={second_exchange['bridge_debug']['activation_transition']['outcome']['handoff_result']}`, "
        f"`bridge_success={second_exchange['bridge_debug']['activation_transition']['outcome']['bridge_success']}`\n"
    )

    print("## Final Session State")
    print(f"- Final response type: `{success_chunk['response_type']}`")
    print(f"- Final bridge phase: `{success_chunk['bridge_phase']}`")
    print(f"- Final current object: `{success_chunk['current_object_name']}`")
    print(f"- Learning anchor active: `{success_chunk['learning_anchor_active']}`\n")

    print("## Transcript Excerpt")
    print(f"1. Model: {transcript['introduction']['content']}")
    print(f"2. Child: {first_exchange['child_response']}")
    print(f"3. Model: {first_exchange['model_response']}")
    print(f"4. Child: {second_exchange['child_response']}")
    print(f"5. Model: {second_exchange['model_response']}")


if __name__ == "__main__":
    main()
