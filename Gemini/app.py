"""
Flask Web Service for Child Learning Assistant (Gemini Version)
Provides REST API endpoints and web interface for the educational chatbot
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import uuid
import os
import database
from child_learning_assistant import ChildLearningAssistant
import prompts
import traceback
import object_classifier

app = Flask(__name__, static_folder='static')
CORS(app)  # Enable CORS for frontend access

# Initialize the database (for sessions only)
database.init_db()


@app.route('/')
def index():
    """Serve the web demo interface"""
    print(f"[DEBUG] Serving index.html from static folder")
    return send_from_directory('static', 'index.html')


@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files with debug logging"""
    print(f"[DEBUG] Serving static file: {filename}")
    return send_from_directory('static', filename)


@app.route('/api/health', methods=['GET'])
def health_check():
    """
    Health check endpoint
    Returns: JSON with status
    """
    return jsonify({
        'status': 'healthy',
        'service': 'Child Learning Assistant (Gemini)',
        'version': '1.0'
    }), 200


@app.route('/api/classify', methods=['POST'])
def classify_object_endpoint():
    """
    Classify an object into a level2 category using LLM.

    Request Body (JSON):
    {
        "object_name": "apple"  # Required: Object to classify
    }

    Returns:
    {
        "success": true,
        "object_name": "apple",
        "recommended_category": "fresh_ingredients",
        "category_display": "Fresh Ingredients",
        "level1_category": "Foods"
    }

    Or if classification fails:
    {
        "success": true,
        "object_name": "airplane",
        "recommended_category": null,
        "message": "Could not classify object into any category"
    }
    """
    try:
        data = request.get_json()
        print(f"[DEBUG] /api/classify called with data: {data}")

        if not data:
            print(f"[ERROR] No JSON data received")
            return jsonify({'success': False, 'error': 'Request body must be JSON'}), 400

        object_name = data.get('object_name')
        if not object_name:
            return jsonify({'success': False, 'error': 'object_name is required'}), 400

        # Classify the object
        recommended_category = object_classifier.classify_object(object_name)

        if recommended_category:
            category_display = object_classifier.get_category_display_name(recommended_category)
            level1_category = object_classifier.LEVEL2_CATEGORIES.get(recommended_category)

            return jsonify({
                'success': True,
                'object_name': object_name,
                'recommended_category': recommended_category,
                'category_display': category_display,
                'level1_category': level1_category
            }), 200
        else:
            return jsonify({
                'success': True,
                'object_name': object_name,
                'recommended_category': None,
                'message': 'Could not classify object into any category'
            }), 200

    except Exception as e:
        print(f"Error in classify_object_endpoint: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': f'Internal server error: {str(e)}'}), 500


@app.route('/api/start', methods=['POST'])
def start_conversation():
    """
    Start a new learning conversation with an object.
    Can be run in production mode (using hardcoded prompts) or
    test mode (providing prompts directly).
    """
    try:
        data = request.get_json()
        print(f"[DEBUG] /api/start called with data: {data}")

        if not data:
            print(f"[ERROR] No JSON data received")
            return jsonify({'success': False, 'error': 'Request body must be JSON'}), 400

        object_name = data.get('object_name')
        category = data.get('category')
        if not object_name or not category:
            return jsonify({'success': False, 'error': 'Both object_name and category are required'}), 400

        # Optional: age and category parameters
        # Note: level1_category is optional and will be auto-detected from level2_category if not provided
        age = data.get('age')
        level1_category = data.get('level1_category')  # Optional - auto-detected from level2
        level2_category = data.get('level2_category')
        level3_category = data.get('level3_category')

        is_test = data.get('is_test', False)

        if is_test:
            # In test mode, prompts must be provided directly
            system_prompt = data.get('system_prompt')
            user_prompt_template = data.get('user_prompt')
            if not system_prompt or not user_prompt_template:
                return jsonify({
                    'success': False,
                    'error': 'In test mode, both system_prompt and user_prompt are required'
                }), 400
        else:
            # In production mode, load hardcoded prompts
            prompts_dict = prompts.get_prompts()
            system_prompt = prompts_dict['system_prompt']
            user_prompt_template = prompts_dict['user_prompt']

        # Create new session
        session_id = str(uuid.uuid4())
        assistant = ChildLearningAssistant()

        # Start conversation with the appropriate prompts
        # The assistant will automatically load all other prompts (hints, reveal, etc.) from hardcoded prompts.py
        response = assistant.start_new_object(
            object_name,
            category,
            system_prompt,
            user_prompt_template,
            age=age,
            level1_category=level1_category,
            level2_category=level2_category,
            level3_category=level3_category
        )

        # Store session in the database
        database.save_session(session_id, assistant)

        print(f"[DEBUG] Session created: {session_id}, Object: {object_name}, Age: {age}, Level2: {level2_category}")

        return jsonify({
            'success': True,
            'session_id': session_id,
            'response': response,
            'object': object_name,
            'category': category
        }), 201

    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        print(f"Error in start_conversation: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': f'Internal server error: {str(e)}'}), 500


@app.route('/api/continue', methods=['POST'])
def continue_conversation():
    """
    Continue an existing conversation

    Request Body (JSON):
    {
        "session_id": "uuid-string",     # Required: Session ID from /start
        "child_response": "I don't know" # Required: Child's response/answer
    }

    Returns:
    {
        "response": "Curious Fox's response",
        "success": true
    }
    """
    try:
        data = request.get_json()
        print(f"[DEBUG] /api/continue called with session: {data.get('session_id', 'N/A')[:8]}...")

        if not data:
            print(f"[ERROR] No JSON data received")
            return jsonify({
                'success': False,
                'error': 'Request body must be JSON'
            }), 400

        session_id = data.get('session_id')
        child_response = data.get('child_response')
        print(f"[DEBUG] Child response: '{child_response}'")

        if not session_id or not child_response:
            return jsonify({
                'success': False,
                'error': 'Both session_id and child_response are required'
            }), 400

        # Get session
        assistant = database.load_session(session_id)
        if not assistant:
            return jsonify({
                'success': False,
                'error': 'Invalid or expired session_id'
            }), 404

        # Continue conversation
        response, mastery_achieved, is_correct, is_neutral, audio_output = assistant.continue_conversation(child_response)

        print(f"[DEBUG] Response generated - Correct: {is_correct}, Mastery: {mastery_achieved}, Count: {assistant.correct_count}")

        # End the session if mastery is achieved
        if mastery_achieved:
            print(f"[DEBUG] Mastery achieved! Deleting session: {session_id[:8]}...")
            database.delete_session(session_id)
        else:
            database.save_session(session_id, assistant)

        emoji_response = response
        # Add emoji only if it's a direct answer, not a hint or the final mastery message
        if not is_neutral and not mastery_achieved:
            if is_correct:
                emoji_response = f"✅ {response}"
            else:
                emoji_response = f"❌ {response}"

        return jsonify({
            'success': True,
            'response': emoji_response,
            'audio_output': audio_output,  # Clean text without emojis for TTS
            'mastery_achieved': mastery_achieved,
            'correct_count': assistant.correct_count,
            'is_correct': is_correct,
            'is_neutral': is_neutral
        }), 200

    except Exception as e:
        print(f"Error in continue_conversation: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': f'Internal server error: {str(e)}'
        }), 500


@app.route('/api/history/<session_id>', methods=['GET'])
def get_history(session_id):
    """
    Get conversation history for a session

    URL Parameter:
        session_id: The session ID

    Returns:
    {
        "session_id": "uuid-string",
        "object": "Banana",
        "category": "Fruit",
        "history": [
            {"role": "system", "content": "..."},
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": "..."}
        ],
        "success": true
    }
    """
    try:
        assistant = database.load_session(session_id)
        if not assistant:
            return jsonify({
                'success': False,
                'error': 'Invalid or expired session_id'
            }), 404

        return jsonify({
            'success': True,
            'session_id': session_id,
            'object': assistant.current_object,
            'category': assistant.current_category,
            'history': assistant.get_conversation_history()
        }), 200

    except Exception as e:
        print(f"Error in get_history: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': f'Internal server error: {str(e)}'
        }), 500


@app.route('/api/reset', methods=['POST'])
def reset_session():
    """
    Reset/delete a session

    Request Body (JSON):
    {
        "session_id": "uuid-string"  # Required: Session ID to reset
    }

    Returns:
    {
        "success": true,
        "message": "Session reset successfully"
    }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                'success': False,
                'error': 'Request body must be JSON'
            }), 400

        session_id = data.get('session_id')

        if not session_id:
            return jsonify({
                'success': False,
                'error': 'session_id is required'
            }), 400

        if database.delete_session(session_id):
            return jsonify({
                'success': True,
                'message': 'Session reset successfully'
            }), 200
        else:
            return jsonify({
                'success': False,
                'error': 'Session not found'
            }), 404

    except Exception as e:
        print(f"Error in reset_session: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': f'Internal server error: {str(e)}'
        }), 500


@app.route('/api/sessions', methods=['GET'])
def list_sessions():
    """
    List all active sessions (for debugging/monitoring)

    Returns:
    {
        "active_sessions": 5,
        "sessions": [
            {
                "session_id": "uuid-1",
                "object": "Banana",
                "category": "Fruit"
            }
        ],
        "success": true
    }
    """
    try:
        all_sessions = database.list_all_sessions()
        session_list = [
            {
                'session_id': s['id'],
                'object': s['current_object'],
                'category': s['current_category']
            }
            for s in all_sessions
        ]

        return jsonify({
            'success': True,
            'active_sessions': len(session_list),
            'sessions': session_list
        }), 200

    except Exception as e:
        print(f"Error in list_sessions: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': f'Internal server error: {str(e)}'
        }), 500


if __name__ == '__main__':
    # Check if static folder exists
    static_path = os.path.join(os.path.dirname(__file__), 'static')
    static_exists = os.path.exists(static_path)

    print("=" * 60)
    print("Child Learning Assistant - Flask Web Service (Gemini)")
    print("=" * 60)
    print(f"\n📁 Static folder: {static_path}")
    print(f"   Exists: {'✅ Yes' if static_exists else '❌ No'}")
    if static_exists:
        files = os.listdir(static_path)
        print(f"   Files: {', '.join(files) if files else 'Empty'}")
    print("\n🌐 Web Interface:")
    print("  http://localhost:5001")
    print("\n📡 API Endpoints:")
    print("  POST   /api/classify   - Classify object into category")
    print("  POST   /api/start      - Start new conversation")
    print("  POST   /api/continue   - Continue conversation")
    print("  GET    /api/history/<session_id> - Get history")
    print("  POST   /api/reset      - Reset session")
    print("  GET    /api/sessions   - List active sessions")
    print("  GET    /api/health     - Health check")
    print("\n" + "=" * 60)
    print("🚀 Server starting on http://localhost:5001")
    print("   Open your browser and visit the URL above!")
    print("=" * 60 + "\n")

    app.run(debug=True, host='0.0.0.0', port=5001)
