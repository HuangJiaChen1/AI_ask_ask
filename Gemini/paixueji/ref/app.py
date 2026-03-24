"""Minimal upstream app demonstrating deep link handoff to WonderLens.

Run:
    pip install fastapi uvicorn
    python app.py

Then open http://localhost:3000 in your browser.

Prerequisites:
    WonderLens backend running on port 8000
    WonderLens frontend running on port 5174
"""

import json
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

app = FastAPI(title="Upstream Demo")

# Where to write handoff files so the WonderLens frontend can fetch them.
# In production this would be an S3 bucket, shared CDN path, etc.
HANDOFF_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "public" / "handoff"
HANDOFF_DIR.mkdir(parents=True, exist_ok=True)

WONDERLENS_URL = "http://localhost:5174"


class HandoffRequest(BaseModel):
    entity: str
    tier: str = "T0"
    conversation: list[dict]


@app.post("/api/handoff")
async def create_handoff(req: HandoffRequest) -> JSONResponse:
    """Save conversation JSON and return the WonderLens redirect URL."""
    filename = f"{uuid.uuid4().hex[:8]}.json"
    filepath = HANDOFF_DIR / filename
    filepath.write_text(json.dumps(req.conversation, indent=2))

    context_path = f"/handoff/{filename}"
    redirect_url = f"{WONDERLENS_URL}/?entity={req.entity}&tier={req.tier}&context={context_path}"

    return JSONResponse({"redirect_url": redirect_url, "context_path": context_path})


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return PAGE_HTML


PAGE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Upstream App Demo</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f0f4f8;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 2rem 1rem;
    color: #1a202c;
  }

  h1 { font-size: 1.4rem; margin-bottom: 0.25rem; }
  .subtitle { color: #718096; font-size: 0.85rem; margin-bottom: 1.5rem; }

  .card {
    background: #fff;
    border-radius: 1rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    width: 100%;
    max-width: 420px;
    overflow: hidden;
  }

  .card-header {
    padding: 1rem 1.25rem;
    background: #edf2f7;
    border-bottom: 1px solid #e2e8f0;
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  .card-header .dot { width: 8px; height: 8px; border-radius: 50%; background: #48bb78; }
  .card-header span { font-size: 0.8rem; color: #4a5568; }

  .chat {
    padding: 1rem 1.25rem;
    min-height: 260px;
    max-height: 360px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }

  .bubble {
    max-width: 85%;
    padding: 0.55rem 0.85rem;
    border-radius: 1rem;
    font-size: 0.88rem;
    line-height: 1.4;
    opacity: 0;
    transform: translateY(6px);
    animation: fadeUp 0.3s ease forwards;
  }
  .bubble.ai {
    background: #ebf4ff;
    color: #2b6cb0;
    align-self: flex-start;
    border-bottom-left-radius: 0.25rem;
  }
  .bubble.child {
    background: #f0fff4;
    color: #276749;
    align-self: flex-end;
    border-bottom-right-radius: 0.25rem;
  }
  .bubble .label {
    font-size: 0.65rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    margin-bottom: 0.15rem;
    opacity: 0.7;
  }

  @keyframes fadeUp {
    to { opacity: 1; transform: translateY(0); }
  }

  .actions {
    padding: 1rem 1.25rem;
    border-top: 1px solid #e2e8f0;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .actions select, .actions button {
    width: 100%;
    padding: 0.6rem;
    border-radius: 0.5rem;
    font-size: 0.85rem;
    border: 1px solid #e2e8f0;
  }

  .row { display: flex; gap: 0.5rem; }
  .row > * { flex: 1; }

  .btn-primary {
    background: #3182ce;
    color: #fff;
    border: none;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s;
  }
  .btn-primary:hover { background: #2b6cb0; }
  .btn-primary:disabled { background: #a0aec0; cursor: not-allowed; }

  .btn-secondary {
    background: #fff;
    color: #4a5568;
    cursor: pointer;
    font-weight: 500;
  }
  .btn-secondary:hover { background: #f7fafc; }

  .status {
    margin-top: 0.75rem;
    font-size: 0.75rem;
    color: #718096;
    text-align: center;
  }
  .status a { color: #3182ce; }
</style>
</head>
<body>

<h1>Upstream App Demo</h1>
<p class="subtitle">Simulated conversation → deep link handoff to WonderLens</p>

<div class="card">
  <div class="card-header">
    <div class="dot"></div>
    <span>Conversation with child</span>
  </div>

  <div class="chat" id="chat"></div>

  <div class="actions">
    <div class="row">
      <select id="entity">
        <option value="dinosaur">Dinosaur</option>
        <option value="dog">Dog</option>
        <option value="cat">Cat</option>
        <option value="ladybug">Ladybug</option>
        <option value="dandelion">Dandelion</option>
      </select>
      <select id="tier">
        <option value="T0">T0 (ages 2-4)</option>
        <option value="T1">T1 (ages 4-6)</option>
        <option value="T2">T2 (ages 6-8)</option>
      </select>
    </div>
    <button class="btn-secondary" id="btnChat" onclick="startChat()">Start Conversation</button>
    <button class="btn-primary" id="btnPlay" onclick="handoff()" disabled>Hand Off to WonderLens</button>
  </div>
</div>

<div class="status" id="status"></div>

<script>
const CONVERSATIONS = {
  dinosaur: [
    { role: 'ai',    text: 'Hi there! I see you found something interesting. What is it?' },
    { role: 'child', text: 'A dinosaur! It has big spikes on its back!' },
    { role: 'ai',    text: 'Wow, those spikes look so cool! What do you think they were for?' },
    { role: 'child', text: 'Maybe to protect it from other dinosaurs!' },
    { role: 'ai',    text: 'Like natural armor — great thinking! Want to play a game with this dinosaur?' },
    { role: 'child', text: 'Yes, let\\'s do it!' },
  ],
  dog: [
    { role: 'ai',    text: 'Oh, who is this fluffy friend?' },
    { role: 'child', text: 'It\\'s a dog! A really happy one!' },
    { role: 'ai',    text: 'It does look happy! What do you think makes this dog so cheerful?' },
    { role: 'child', text: 'Maybe someone is playing with it!' },
    { role: 'ai',    text: 'That\\'s a lovely thought! Would you like to play a mood game with this dog?' },
    { role: 'child', text: 'Yes please!' },
  ],
  cat: [
    { role: 'ai',    text: 'Look at this little creature. What do you see?' },
    { role: 'child', text: 'A cat! It has big green eyes!' },
    { role: 'ai',    text: 'Those eyes are beautiful. What do you think the cat is dreaming about?' },
    { role: 'child', text: 'Maybe it\\'s dreaming about catching fish!' },
    { role: 'ai',    text: 'A fish dream — how fun! Want to explore this cat\\'s dreams together?' },
    { role: 'child', text: 'Yeah!' },
  ],
  ladybug: [
    { role: 'ai',    text: 'Something tiny caught your eye! What is it?' },
    { role: 'child', text: 'A ladybug with lots of dots!' },
    { role: 'ai',    text: 'Ooh, can you count how many dots it has?' },
    { role: 'child', text: 'I see seven dots!' },
    { role: 'ai',    text: 'Seven dots — great counting! Want to go on a dot-finding adventure?' },
    { role: 'child', text: 'Yes!' },
  ],
  dandelion: [
    { role: 'ai',    text: 'You found something in the garden! What is it?' },
    { role: 'child', text: 'A fluffy white flower!' },
    { role: 'ai',    text: 'That\\'s a dandelion! What happens when you blow on it?' },
    { role: 'child', text: 'The fluffy bits fly away like tiny parachutes!' },
    { role: 'ai',    text: 'Tiny parachutes — what a great way to describe it! Want to go on a fluffy expedition?' },
    { role: 'child', text: 'Yes, let\\'s go!' },
  ],
};

let currentConversation = [];
let chatStarted = false;

function startChat() {
  const entity = document.getElementById('entity').value;
  const chat = document.getElementById('chat');
  const btnChat = document.getElementById('btnChat');
  const btnPlay = document.getElementById('btnPlay');
  const status = document.getElementById('status');

  chat.innerHTML = '';
  status.textContent = '';
  currentConversation = [];
  chatStarted = true;
  btnChat.disabled = true;
  btnPlay.disabled = true;

  const turns = CONVERSATIONS[entity] || CONVERSATIONS.dinosaur;

  turns.forEach((turn, i) => {
    setTimeout(() => {
      currentConversation.push(turn);

      const bubble = document.createElement('div');
      bubble.className = `bubble ${turn.role}`;
      bubble.style.animationDelay = '0s';

      const label = document.createElement('div');
      label.className = 'label';
      label.textContent = turn.role === 'ai' ? 'AI' : 'Child';
      bubble.appendChild(label);

      const text = document.createElement('div');
      text.textContent = turn.text;
      bubble.appendChild(text);

      chat.appendChild(bubble);
      chat.scrollTop = chat.scrollHeight;

      // Enable handoff button after last turn
      if (i === turns.length - 1) {
        setTimeout(() => {
          btnPlay.disabled = false;
          btnChat.disabled = false;
          status.textContent = 'Conversation complete — ready to hand off.';
        }, 400);
      }
    }, (i + 1) * 800);
  });
}

async function handoff() {
  const entity = document.getElementById('entity').value;
  const tier = document.getElementById('tier').value;
  const btnPlay = document.getElementById('btnPlay');
  const status = document.getElementById('status');

  btnPlay.disabled = true;
  status.textContent = 'Saving conversation and redirecting...';

  try {
    const res = await fetch('/api/handoff', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ entity, tier, conversation: currentConversation }),
    });

    if (!res.ok) throw new Error(`Handoff failed: ${res.status}`);
    const data = await res.json();

    status.innerHTML = `Redirecting to <a href="${data.redirect_url}">${data.redirect_url}</a>`;

    // Redirect to WonderLens
    window.location.href = data.redirect_url;
  } catch (err) {
    status.textContent = `Error: ${err.message}`;
    btnPlay.disabled = false;
  }
}
</script>
</body>
</html>
"""


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3300)
