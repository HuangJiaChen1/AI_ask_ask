# Quick Start - Web Demo

Get the Child Learning Assistant web demo running in 3 simple steps!

## Prerequisites

- ✅ Python 3.7+ installed
- ✅ Gemini API key configured in `config.json`
- ✅ Dependencies installed (`pip install -r requirements.txt`)

## Step 1: Start the Server

```bash
python app.py
```

You should see:
```
============================================================
Child Learning Assistant - Flask Web Service (Gemini)
============================================================

🌐 Web Interface:
  http://localhost:5001

📡 API Endpoints:
  POST   /api/start      - Start new conversation
  POST   /api/continue   - Continue conversation
  ...

============================================================
🚀 Server starting on http://localhost:5001
   Open your browser and visit the URL above!
============================================================
```

## Step 2: Open Your Browser

Navigate to: **http://localhost:5001**

You'll see a beautiful purple interface with a form!

## Step 3: Try It Out!

**Example 1: Simple Session**
1. Object name: `banana`
2. Age: `6`
3. Level 2 category: `fresh_ingredients`
4. Click "Start Learning!"
5. Answer the AI's questions!

**Example 2: With Animals**
1. Object name: `dog`
2. Age: `5`
3. Level 2 category: `vertebrates`
4. Level 3 category: `mammals`
5. Start chatting!

**Example 3: Younger Child**
1. Object name: `apple`
2. Age: `4`
3. Level 2 category: `fresh_ingredients`
4. Expect simple "what color" type questions

**Example 4: Older Child**
1. Object name: `tree`
2. Age: `8`
3. Level 2 category: `wild_natural_plants`
4. Expect "why" questions about growth and ecology

## What to Expect

### Initial Question
The AI will ask an age-appropriate question:
- **Age 4:** "What color is a banana?"
- **Age 6:** "How does a banana grow?"
- **Age 8:** "Why do bananas turn brown when they get old?"

### Conversation Flow
1. AI asks a question
2. You type an answer
3. AI gives feedback (✅ or ❌)
4. AI asks next question
5. Repeat until mastery!

### Mastery Achievement
- Answer 4 questions correctly
- Progress bar fills up
- Celebration animation appears!
- Start a new session to continue learning

## Available Categories

### Foods
- `fresh_ingredients` - fruits, vegetables, raw foods
- `processed_foods` - cooked/packaged foods
- `beverages_drinks` - water, juice, milk, etc.

### Animals
- `vertebrates` - animals with backbones (fish, birds, mammals)
- `invertebrates` - animals without backbones (insects, worms)
- `human_raised_animals` - pets and farm animals

### Plants
- `ornamental_plants` - flowers, decorative plants
- `useful_plants` - food plants, herbs, medicinal plants
- `wild_natural_plants` - plants that grow wild

## Tips

### For Best Results:
- ✅ Provide the child's age for age-appropriate questions
- ✅ Choose a level 2 category for topic-specific questions
- ✅ Encourage the child to think before answering
- ✅ If stuck, say "I don't know" for hints

### Hints System:
1. First "I don't know" → Easier related question
2. Second "I don't know" → Even easier question
3. Third "I don't know" → Answer revealed

### Progress Tracking:
- Green ✅ = Correct answer
- Red ❌ = Incorrect answer
- Progress bar shows 0/4, 1/4, 2/4, 3/4, 4/4
- At 4/4 → Mastery achieved! 🎉

## Troubleshooting

**Server won't start?**
- Check if port 5001 is available
- Make sure `config.json` has your API key

**Page won't load?**
- Verify server is running
- Check the URL: `http://localhost:5001` (not 5000!)
- Clear browser cache if needed

**API errors?**
- Check server console for error messages
- Verify API key is valid in `config.json`
- Check internet connection

## That's It!

You're now ready to use the Child Learning Assistant web demo! 🚀

For more details, see:
- **Full documentation:** `WEB_SERVICE_DOCUMENTATION.md`
- **API details:** Check the API Reference section
- **Customization:** Edit `prompts.py` and `category_prompts.json`

Have fun learning! 🎓✨
