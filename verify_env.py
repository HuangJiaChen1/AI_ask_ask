import sys
import os

print(f"Python Executable: {sys.executable}")
print(f"Python Version: {sys.version}")
print(f"Current Working Directory: {os.getcwd()}")
print("\nSys Path:")
for p in sys.path:
    print(p)

try:
    import loguru
    print(f"\nLoguru found at: {loguru.__file__}")
except ImportError:
    print("\nLoguru NOT found!")
