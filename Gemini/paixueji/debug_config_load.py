
from paixueji_assistant import PaixuejiAssistant

assistant = PaixuejiAssistant()
print(f"Original config model_name: {assistant.config.get('model_name')}")
print(f"Original config model: {assistant.config.get('model')}")

config = assistant.config
# Mimic the line in simulate_theme_guide.py
config["model_name"] = config.get("model_name", "gemini-2.5-flash-lite")

print(f"Modified config model_name: {config.get('model_name')}")
