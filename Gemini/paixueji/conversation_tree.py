"""
Conversation Flow Tree for Debugging

This module provides a tree structure to track conversation flow for debugging purposes.
Each node captures decision points, validation results, and state changes.
"""

import time
from datetime import datetime


class ConversationTreeNode:
    """Represents a single node in the conversation flow tree."""

    def __init__(self, node_id, parent_id, turn_number, node_type):
        """
        Initialize a tree node.

        Args:
            node_id: Unique identifier for this node
            parent_id: ID of parent node (None for root)
            turn_number: Turn number in conversation (0-indexed)
            node_type: Type of response (introduction, followup, explanation, gentle_correction)
        """
        self.node_id = node_id
        self.parent_id = parent_id
        self.timestamp = time.time()
        self.turn_number = turn_number
        self.type = node_type

        # Core conversation data
        self.user_input = None
        self.ai_response = None
        self.ai_response_part1 = None  # Feedback / Explanation
        self.ai_response_part2 = None  # Follow-up Question
        self.response_duration = 0.0

        # State tracking (before/after snapshots)
        self.state_before = {}
        self.state_after = {}

        # Validation results
        self.validation = None

        # Decision tracking (topic switching, routing)
        self.decision = None

        # Metadata (token usage, chunk count, etc.)
        self.metadata = {}

    def to_dict(self):
        """Convert node to dictionary for JSON serialization."""
        return {
            "node_id": self.node_id,
            "parent_id": self.parent_id,
            "timestamp": datetime.fromtimestamp(self.timestamp).isoformat(),
            "turn_number": self.turn_number,
            "type": self.type,
            "user_input": self.user_input,
            "ai_response": self.ai_response,
            "ai_response_part1": self.ai_response_part1,
            "ai_response_part2": self.ai_response_part2,
            "response_duration": round(self.response_duration, 3),
            "state_before": self.state_before,
            "state_after": self.state_after,
            "validation": self.validation,
            "decision": self.decision,
            "metadata": self.metadata
        }


class ConversationFlowTree:
    """Manages the conversation flow tree for debugging."""

    def __init__(self, session_id, metadata):
        """
        Initialize conversation flow tree.

        Args:
            session_id: Session ID for this conversation
            metadata: Initial metadata (created_at, initial_object, child_age, etc.)
        """
        self.session_id = session_id
        self.metadata = metadata
        self.nodes = []
        self.node_counter = 0

    def create_node(self, parent_id, turn_number, node_type):
        """
        Create a new node and add to tree.

        Args:
            parent_id: ID of parent node (None for root)
            turn_number: Turn number in conversation
            node_type: Type of response

        Returns:
            ConversationTreeNode: The newly created node
        """
        node_id = f"node_{self.node_counter:04d}"
        self.node_counter += 1

        node = ConversationTreeNode(node_id, parent_id, turn_number, node_type)
        self.nodes.append(node)
        return node

    def get_latest_node(self):
        """
        Get the most recently created node.

        Returns:
            ConversationTreeNode or None: Latest node or None if tree is empty
        """
        return self.nodes[-1] if self.nodes else None

    def to_json(self, compact=False):
        """
        Export tree as JSON.

        Args:
            compact: If True, truncate AI responses to 50 chars for smaller output

        Returns:
            dict: JSON-serializable tree structure
        """
        nodes_data = []
        for node in self.nodes:
            node_dict = node.to_dict()
            if compact and node_dict.get('ai_response'):
                node_dict['ai_response'] = node_dict['ai_response'][:50] + '...'
            nodes_data.append(node_dict)

        return {
            "session_id": self.session_id,
            "metadata": self.metadata,
            "node_count": len(self.nodes),
            "nodes": nodes_data
        }
