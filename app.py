"""
Flask Web Service for Child Learning Assistant
Provides REST API endpoints for the educational chatbot
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import uuid
import database
from child_learning_assistant import ChildLearningAssistant
import traceback

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend access

# Initialize the database
database.init_db()


@app.route('/api/health', methods=['GET'])
def health_check():
    """
    Health check endpoint
    Returns: JSON with status
    """
    return jsonify({
        'status': 'healthy',
        'service': 'Child Learning Assistant',
        'version': '1.0'
    }), 200


@app.route('/api/start', methods=['POST'])
def start_conversation():
    """
    Start a new learning conversation with an object.
    Can be run in production mode (using prompts from DB) or
    test mode (providing prompts directly).
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body must be JSON'}), 400

        object_name = data.get('object_name')
        category = data.get('category')
        if not object_name or not category:
            return jsonify({'success': False, 'error': 'Both object_name and category are required'}), 400

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
            # In production mode, load prompts from the database (like demo.py)
            prompts = database.get_prompts()
            if not prompts:
                return jsonify({
                    'success': False,
                    'error': 'Production prompts not found in the database. Please run database.init_db() first.'
                }), 500
            system_prompt = prompts['system_prompt']
            user_prompt_template = prompts['user_prompt']

        # Create new session
        session_id = str(uuid.uuid4())
        assistant = ChildLearningAssistant()

        # Start conversation with the appropriate prompts
        # The assistant will automatically load all other prompts (hints, reveal, etc.) from database
        response = assistant.start_new_object(
            object_name,
            category,
            system_prompt,
            user_prompt_template
        )

        # Store session in the database
        database.save_session(session_id, assistant)

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

        if not data:
            return jsonify({
                'success': False,
                'error': 'Request body must be JSON'
            }), 400

        session_id = data.get('session_id')
        child_response = data.get('child_response')

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
        response, mastery_achieved, is_correct, is_neutral = assistant.continue_conversation(child_response)

        # End the session if mastery is achieved
        if mastery_achieved:
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


@app.route('/api/update_prompt', methods=['POST'])
def update_prompt():
    """
    Update the production prompts in the database.

    Request Body (JSON) - All fields are optional:
    {
        "system_prompt": "You are a helpful assistant...",
        "user_prompt": "The user wants to learn about {object_name}...",
        "initial_question_prompt": "Generate an exciting first question...",
        "hint_prompt": "The child is stuck on this question...",
        "reveal_prompt": "The child was asked...",
        "state_instructions_json": "{...}"
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body must be JSON'}), 400

        # Extract all possible prompt fields (all optional)
        system_prompt = data.get('system_prompt')
        user_prompt = data.get('user_prompt')
        initial_question_prompt = data.get('initial_question_prompt')
        hint_prompt = data.get('hint_prompt')
        reveal_prompt = data.get('reveal_prompt')
        state_instructions_json = data.get('state_instructions_json')

        # At least one field must be provided
        if not any([system_prompt, user_prompt, initial_question_prompt, hint_prompt, reveal_prompt, state_instructions_json]):
            return jsonify({'success': False, 'error': 'At least one prompt field must be provided'}), 400

        # Update only the provided fields
        database.update_prompts(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            initial_question_prompt=initial_question_prompt,
            hint_prompt=hint_prompt,
            reveal_prompt=reveal_prompt,
            state_instructions_json=state_instructions_json
        )

        return jsonify({'success': True, 'message': 'Prompts updated successfully'}), 200

    except Exception as e:
        print(f"Error in update_prompt: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': f'Internal server error: {str(e)}'}), 500


if __name__ == '__main__':
    print("=" * 60)
    print("Child Learning Assistant - Flask Web Service")
    print("=" * 60)
    print("\nAPI Endpoints:")
    print("  POST   /api/start      - Start new conversation")
    print("  POST   /api/continue   - Continue conversation")
    print("  GET    /api/history/<session_id> - Get history")
    print("  POST   /api/reset      - Reset session")
    print("  GET    /api/sessions   - List active sessions")
    print("  GET    /api/health     - Health check")
    print("\n" + "=" * 60)
    print("Server starting on http://localhost:5000")
    print("=" * 60 + "\n")

    app.run(debug=True, host='0.0.0.0', port=5001)
