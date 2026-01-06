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
    
    def generate_text_report(self) -> str:
        """
        Generate a human-readable text report of the conversation flow for debugging.
        Replacing raw server logs with a structured narrative of logic and state.
        """
        lines = []
        
        # --- HEADER ---
        lines.append("=" * 80)
        lines.append(f"📄 PAIXUEJI DEBUG LOG")
        lines.append(f"Session ID: {self.session_id}")
        lines.append(f"Generated:  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Format Metadata nicely
        meta = self.metadata or {}
        lines.append("-" * 80)
        lines.append(f"INITIAL CONFIGURATION:")
        lines.append(f"• Age:    {meta.get('child_age', 'N/A')}")
        lines.append(f"• Object: {meta.get('initial_object', 'N/A')}")
        lines.append(f"• Tone:   {meta.get('tone', 'N/A')}")
        lines.append(f"• Focus:  {meta.get('initial_focus', 'N/A')}")
        lines.append("=" * 80)
        lines.append("")

        # --- NODES (TURNS) ---
        for node in self.nodes:
            # Timestamp relative to conversation start (if possible) or absolute
            ts = datetime.fromtimestamp(node.timestamp).strftime('%H:%M:%S')
            
            lines.append(f"[TURN {node.turn_number}] {node.type.upper()} ({ts})")
            lines.append("-" * 80)

            # 1. INPUT & CONTEXT
            # Show what the system 'knew' before processing
            sb = node.state_before or {}
            ctx_info = [
                f"Object: {sb.get('object_name')}",
                f"Focus: {sb.get('focus_mode')}",
                f"Score: {sb.get('correct_answer_count')}"
            ]
            lines.append(f"🧠 CONTEXT:  {' | '.join(ctx_info)}")
            
            input_text = node.user_input if node.user_input else "(System Trigger / Start)"
            lines.append(f"👤 INPUT:    {input_text}")
            lines.append("")

            # 2. LOGIC (The "Why")
            # Combine Validation and Decision to show the thought process
            val = node.validation or {}
            dec = node.decision or {}
            
            if val or dec:
                lines.append("🔍 LOGIC ANALYSIS:")
                
                # Validation Details
                if val:
                    is_engaged = val.get('is_engaged')
                    is_correct = val.get('is_factually_correct')
                    
                    status = "UNKNOWN"
                    if is_engaged is False: status = "❌ STUCK / NOT ENGAGED"
                    elif is_correct is True: status = "✅ CORRECT"
                    elif is_correct is False: status = "⚠️ WRONG"
                    
                    lines.append(f"   • Validation: {status}")
                    if val.get('correctness_reasoning'):
                        lines.append(f"   • Reasoning:  {val.get('correctness_reasoning')}")

                # Decision Details (Switching)
                if dec:
                    d_type = dec.get('decision_type', 'N/A')
                    lines.append(f"   • Decision:   {d_type}")
                    
                    if dec.get('detected_object'):
                        lines.append(f"   • Detected:   {dec.get('detected_object')}")
                    
                    if dec.get('switch_reasoning'):
                        lines.append(f"   • Reasoning:  {dec.get('switch_reasoning')}")
                lines.append("")

            # 3. OUTPUT (The Result)
            lines.append("🤖 AI RESPONSE:")
            
            # Check for split response (part 1 = feedback, part 2 = question)
            if node.ai_response_part1 or node.ai_response_part2:
                if node.ai_response_part1:
                    lines.append(f"   [Feedback]: \"{node.ai_response_part1}\"")
                if node.ai_response_part2:
                    lines.append(f"   [Question]: \"{node.ai_response_part2}\"")
            else:
                # Fallback for standard response
                lines.append(f"   \"{node.ai_response}\"")

            # 4. STATE CHANGES
            # Only show what changed
            sa = node.state_after or {}
            changes = []
            for k, v in sa.items():
                old_v = sb.get(k)
                if v != old_v:
                    changes.append(f"{k}: {old_v} -> {v}")
            
            if changes:
                lines.append("")
                lines.append(f"⚙️ STATE UPDATES: {', '.join(changes)}")

            lines.append("=" * 80)
            lines.append("")

        return "\n".join(lines)
