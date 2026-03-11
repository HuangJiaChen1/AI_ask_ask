
from paixueji_assistant import PaixuejiAssistant

assistant = PaixuejiAssistant()
print(f"Original config model_name: {assistant.config.get('model_name')}")
print(f"Original config model: {assistant.config.get('model')}")

config = assistant.config
# Mimic the line in simulate_theme_guide.py

print(f"Modified config model_name: {config.get('model_name')}")
