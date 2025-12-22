# Child Learning Assistant

An interactive educational assistant for young children (ages 4-8) that uses the Qwen AI model to ask suggestive questions about everyday objects, encouraging curiosity and learning.

## Features

- **Educational Questions**: Generates 5 age-appropriate questions per object
- **Conversation Memory**: Maintains context throughout the conversation
- **Adaptive Responses**: Provides explanations when children say "I don't know" and continues with follow-up questions
- **Child-Friendly**: Uses simple language and encouraging tone
- **Web API**: RESTful API for web/mobile integration
- **Session Management**: Support for multiple concurrent conversations

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API Key

Open `config.json` and replace `YOUR_API_KEY_HERE` with your Qwen API key:

```json
{
  "qwen_api_key": "your-actual-api-key",
  "model_name": "qwen-plus",
  "api_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "temperature": 0.7,
  "max_tokens": 1000
}
```

## Usage

### Running the Interactive Demo

```bash
python demo.py
```

The demo will prompt you to:
1. Enter an object name (e.g., "Apple")
2. Enter the object category (e.g., "Fruit")
3. The assistant will start asking educational questions
4. Simulate the child's responses to continue the conversation

### Example Session

```
Enter object name: Apple
Enter object category: Fruit

🤖 Assistant: Hi! Let's learn about apples together!
Do you know what color apples can be?

👦 Child's response: Red?

🤖 Assistant: Yes! Apples can be red! They can also be green
and yellow too. Have you ever eaten a green apple? They taste
a bit different from red ones!

Now, do you know how many ways we can eat an apple?

👦 Child's response: I don't know

🤖 Assistant: That's okay! There are so many fun ways! We can
eat apples fresh and crunchy, we can make them into applesauce,
we can bake them in pies, or even dry them to make apple chips!
Which way sounds most yummy to you?
```

### Running the Web Service (Flask API)

For web/mobile applications, use the Flask web service:

```bash
python app.py
```

The API will start on `http://localhost:5000`

**Available Endpoints:**
- `POST /api/start` - Start new conversation
- `POST /api/continue` - Continue conversation
- `GET /api/history/<session_id>` - Get conversation history
- `POST /api/reset` - Reset session
- `GET /api/sessions` - List active sessions
- `GET /api/health` - Health check

**Quick Example:**
```bash
# Start conversation
curl -X POST http://localhost:5000/api/start \
  -H "Content-Type: application/json" \
  -d '{"object_name": "Banana", "category": "Fruit"}'

# Response includes session_id and first question
# {"session_id": "abc-123", "response": "WOW a banana! ..."}

# Continue conversation
curl -X POST http://localhost:5000/api/continue \
  -H "Content-Type: application/json" \
  -d '{"session_id": "abc-123", "child_response": "I don'\''t know"}'
```

**Test the API:**
```bash
python test_api.py
```

See [API_DOCUMENTATION.md](API_DOCUMENTATION.md) for complete API reference with all arguments and response formats.

## Using in Your Own Code

```python
from Qwen.paixueji.child_learning_assistant import ChildLearningAssistant

# Initialize the assistant
assistant = ChildLearningAssistant()

# Start learning about an object
response = assistant.start_new_object("Apple", "Fruit")
print(response)

# Continue the conversation
response = assistant.continue_conversation("I don't know")
print(response)

# Get conversation history
history = assistant.get_conversation_history()

# Reset for a new object
assistant.reset()
```

## Configuration Options

- `qwen_api_key`: Your Qwen API key from Alibaba Cloud
- `model_name`: Qwen model to use (default: "qwen-plus")
- `api_base_url`: API endpoint (default: Qwen compatible mode)
- `temperature`: Response randomness 0.0-1.0 (default: 0.7)
- `max_tokens`: Maximum response length (default: 1000)

## Project Structure

```
AI_ask_ask/
├── child_learning_assistant.py  # Main assistant class
├── app.py                        # Flask web service
├── demo.py                       # Interactive CLI demo
├── test_api.py                   # API test script
├── config.json                   # Configuration file
├── requirements.txt              # Python dependencies
├── README.md                     # This file
└── API_DOCUMENTATION.md          # Complete API reference
```

## How It Works

1. **System Prompt**: The assistant uses a carefully designed system prompt that ensures child-friendly, educational interactions
2. **Conversation Memory**: All messages are stored in conversation history, allowing the model to maintain context
3. **Adaptive Learning**: When a child says "I don't know", the assistant provides a simple explanation and asks a related follow-up question
4. **Suggestive Questions**: Questions are designed to encourage thinking, observation, and curiosity rather than just testing knowledge

## Tips for Best Results

- Use common, everyday objects that children encounter
- Categories help the model provide more relevant questions (e.g., "Fruit", "Animal", "Toy", "Vehicle")
- Encourage open-ended responses from children
- The assistant adapts to the child's knowledge level throughout the conversation
