import sys
import os

# Ensure we can import from the current directory
sys.path.append(os.getcwd())

try:
    from graph import paixueji_graph
    
    # Generate the Mermaid diagram syntax
    mermaid_code = paixueji_graph.get_graph().draw_mermaid()
    print(mermaid_code)
    
except ImportError as e:
    print(f"Error importing graph: {e}")
except Exception as e:
    print(f"Error generating visualization: {e}")
