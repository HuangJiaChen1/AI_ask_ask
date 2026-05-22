"""
Regression test: after fun_fact removal, no Python source file should contain
fun_fact-related identifiers (except documentation files).
"""
import subprocess
import pytest


def test_no_fun_fact_references_in_python_source():
    """
    Search the main source tree for any residual fun_fact references.
    Excludes docs/, .claude/, __pycache__/, and .pyc files.
    """
    result = subprocess.run(
        [
            "grep", "-r", "-n",
            "--include=*.py",
            "-E", r"fun.?fact|real_facts",
            "stream/", "graph.py", "paixueji_app.py", "schema.py",
            "prompt_optimizer.py", "trace_schema.py", "trace_assembler.py",
            "paixueji_prompts.py",
        ],
        capture_output=True,
        text=True,
    )

    # grep returns exit code 1 when no matches found (which is what we want)
    if result.returncode == 0:
        pytest.fail(
            f"fun_fact references still found in source:\n{result.stdout}"
        )
    assert result.returncode == 1, (
        f"grep failed unexpectedly: stderr={result.stderr}"
    )
