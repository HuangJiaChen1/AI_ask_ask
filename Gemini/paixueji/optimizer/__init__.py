"""
DSPy-inspired prompt optimizer for Paixueji.

Sub-modules:
  metric         — cosine similarity scoring with LLM synthesis fallback
  backward_pass  — TextGrad-C clause-level gradient computation
  bootstrap      — golden example library for few-shot injection
  trigger        — trace loading/grouping for UI and optimization trigger
  convergence_loop — full Hybrid B+C optimization loop
"""
