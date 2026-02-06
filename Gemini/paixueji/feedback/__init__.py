"""
Automated Chatbot Feedback Pipeline
====================================

Replaces the manual loop of: play -> find bad response -> describe to AI -> analyze -> fix -> repeat

Architecture (mirrors RLHF concepts for prompt-driven systems):
- Child Simulator   = Training data generation (replaces manual "playing")
- LLM-as-Judge      = Reward model (replaces manual "finding bad responses")
- Pattern Analyzer   = Diagnosis engine (replaces manual "describing the problem")
- Prompt Optimizer   = Policy optimization (replaces manual "proposing a fix")

Usage:
    cd Gemini/paixueji
    python -m feedback.run_pipeline [options]
"""
