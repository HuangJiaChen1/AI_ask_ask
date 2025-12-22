# Deployment Guide for Ask Ask Assistant

## Overview

This guide covers multiple deployment options for the Ask Ask web demo, from quick temporary sharing to production-ready deployments.

---

## Option 1: Ngrok (Quickest - 5 minutes) ⚡

**Best for:** Quick testing, temporary sharing, demo purposes

### Pros:
- ✅ Fastest setup (< 5 minutes)
- ✅ No server configuration needed
- ✅ HTTPS automatically provided
- ✅ Works from your local machine

### Cons:
- ❌ Only works while your computer is on
- ❌ Free tier has random URLs (changes on restart)
- ❌ Limited connections on free tier

### Setup Steps:

1. **Install ngrok:**
   ```bash
   # Download from https://ngrok.com/download
   # Or use package manager:
   choco install ngrok  # Windows (Chocolatey)
   brew install ngrok   # macOS (Homebrew)
   ```

2. **Sign up for free account:**
   - Go to https://ngrok.com/signup
   - Get your authtoken from dashboard

3. **Configure ngrok:**
   ```bash
   ngrok config add-authtoken YOUR_AUTH_TOKEN
   ```

4. **Start your Flask server:**
   ```bash
   python app.py
   ```

5. **In a new terminal, start ngrok:**
   ```bash
   ngrok http 5001
   ```

6. **Share the URL:**
   - Ngrok will display a URL like: `https://abc123.ngrok-free.app`
   - Send this URL to anyone you want to share with
   - They can access it immediately!

### Important Notes:
- Keep both terminals running (Flask + ngrok)
- URL changes each time you restart ngrok (unless you pay for static domain)
- Free tier may show ngrok banner to users

---

## Option 2: Railway.app (Easy Cloud - 15 minutes) 🚂

**Best for:** Permanent deployment, production use, always-online

### Pros:
- ✅ Always online (24/7)
- ✅ Automatic HTTPS
- ✅ Free tier available ($5 credit/month)
- ✅ Git-based deployment (automatic updates)
- ✅ Custom domain support

### Cons:
- ❌ Requires Railway account
- ❌ Uses cloud resources (costs after free tier)
- ❌ Sessions lost on restart (in-memory storage)

### Setup Steps:

1. **Prepare your repository:**

   Create `.railwayignore` file:
   ```
   __pycache__/
   *.pyc
   .env
   *.db
   logs/
   venv/
   .git/
   ```

   Create `Procfile` (for Railway to know how to start app):
   ```
   web: python app.py
   ```

   Update `app.py` to use PORT from environment:
   ```python
   if __name__ == '__main__':
       port = int(os.environ.get('PORT', 5001))
       app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
   ```

   Create `runtime.txt` (specify Python version):
   ```
   python-3.11.0
   ```

2. **Push to GitHub:**
   ```bash
   git add .
   git commit -m "Prepare for Railway deployment"
   git push origin main
   ```

3. **Deploy to Railway:**
   - Go to https://railway.app
   - Sign up with GitHub
   - Click "New Project" → "Deploy from GitHub repo"
   - Select your repository
   - Railway will auto-detect Flask app and deploy!

4. **Add environment variables:**
   - In Railway dashboard → Variables
   - Add: `GEMINI_API_KEY=your_api_key_here`
   - Railway will restart automatically

5. **Get your URL:**
   - Railway provides: `https://your-app.up.railway.app`
   - Or add custom domain in settings

### Cost Estimate:
- Free tier: $5 credit/month (usually enough for light use)
- After that: ~$5-10/month for small app

---

## Option 3: Render.com (Easy Cloud Alternative) 🎨

**Best for:** Similar to Railway, free tier available

### Pros:
- ✅ Free tier (more generous than Railway)
- ✅ Always online
- ✅ Automatic HTTPS
- ✅ Git-based deployment

### Cons:
- ❌ Free tier sleeps after 15min inactivity (cold start)
- ❌ Slower cold start (~30 seconds)

### Setup Steps:

1. **Create `render.yaml`:**
   ```yaml
   services:
     - type: web
       name: ask-ask-assistant
       env: python
       buildCommand: pip install -r requirements.txt
       startCommand: python app.py
       envVars:
         - key: PORT
           sync: false
         - key: GEMINI_API_KEY
           sync: false
   ```

2. **Update `app.py`:**
   ```python
   if __name__ == '__main__':
       port = int(os.environ.get('PORT', 5001))
       app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
   ```

3. **Push to GitHub**

4. **Deploy on Render:**
   - Go to https://render.com
   - Sign up with GitHub
   - New Web Service → Connect repository
   - Render auto-detects settings
   - Add `GEMINI_API_KEY` in environment variables
   - Deploy!

5. **Get URL:**
   - Render provides: `https://your-app.onrender.com`

### Cost:
- Free tier available
- Paid: $7/month for always-on instance

---

## Option 4: Google Cloud Run (Scalable) ☁️

**Best for:** Production use, high traffic, Google ecosystem

### Pros:
- ✅ Pay per use (very cheap for low traffic)
- ✅ Auto-scales (handles traffic spikes)
- ✅ Free tier: 2 million requests/month
- ✅ Fast cold starts

### Cons:
- ❌ More complex setup
- ❌ Requires Docker knowledge
- ❌ Google Cloud account needed

### Setup Steps:

1. **Create `Dockerfile`:**
   ```dockerfile
   FROM python:3.11-slim

   WORKDIR /app

   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt

   COPY . .

   ENV PORT=8080
   EXPOSE 8080

   CMD ["python", "app.py"]
   ```

2. **Update `app.py`:**
   ```python
   if __name__ == '__main__':
       port = int(os.environ.get('PORT', 8080))
       app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
   ```

3. **Install Google Cloud CLI:**
   ```bash
   # Follow: https://cloud.google.com/sdk/docs/install
   ```

4. **Deploy:**
   ```bash
   gcloud auth login
   gcloud config set project YOUR_PROJECT_ID
   gcloud run deploy ask-ask --source . --region us-central1 --allow-unauthenticated
   ```

5. **Set environment variables:**
   ```bash
   gcloud run services update ask-ask \
     --set-env-vars GEMINI_API_KEY=your_api_key
   ```

### Cost:
- Free tier: 2M requests/month
- After: ~$0.40 per 1M requests (very cheap)

---

## Option 5: Local Network (For Testing) 🏠

**Best for:** Testing with people on same WiFi

### Steps:

1. **Find your local IP:**
   ```bash
   # Windows
   ipconfig
   # Look for IPv4 Address (e.g., 192.168.1.100)

   # macOS/Linux
   ifconfig
   # or
   ip addr show
   ```

2. **Update `app.py` to allow external connections:**
   ```python
   app.run(host='0.0.0.0', port=5001, debug=True, threaded=True)
   ```

3. **Start server:**
   ```bash
   python app.py
   ```

4. **Share your local IP:**
   - Others on same WiFi can access: `http://192.168.1.100:5001`
   - (Replace with your actual IP)

5. **Firewall considerations:**
   - Windows: Allow Python through firewall when prompted
   - Or manually add firewall rule for port 5001

### Limitations:
- Only works on same WiFi network
- Your computer must stay on
- Not secure for internet sharing

---

## 🎯 Recommended Approach

### For Quick Demo (Today):
**Use Option 1 (Ngrok)**
- Setup in 5 minutes
- Share URL immediately
- No account/configuration needed

### For Production (Permanent):
**Use Option 2 (Railway) or Option 3 (Render)**
- Railway: Better performance, $5 free credit
- Render: More generous free tier, but slower cold starts

### For Enterprise (High Traffic):
**Use Option 4 (Google Cloud Run)**
- Best scalability
- Cheapest at scale
- Production-grade reliability

---

## 📋 Pre-Deployment Checklist

Before deploying, make sure:

- [ ] **Remove debug mode:** Set `debug=False` in `app.py`
- [ ] **Secure API key:** Use environment variables, never hardcode
- [ ] **Update CORS:** Restrict origins if needed (currently allows all)
- [ ] **Add rate limiting:** Consider adding Flask-Limiter for production
- [ ] **Test locally:** Verify everything works before deploying
- [ ] **Update config.json:** Ensure API key is not committed to git

### Security Improvements for Production:

1. **Add `.env` file for secrets:**
   ```bash
   # .env
   GEMINI_API_KEY=your_key_here
   ```

2. **Update `config.json` to read from env:**
   ```python
   import os
   from dotenv import load_dotenv

   load_dotenv()
   config['gemini_api_key'] = os.environ.get('GEMINI_API_KEY')
   ```

3. **Add to `.gitignore`:**
   ```
   .env
   config.json
   __pycache__/
   *.pyc
   logs/
   ```

4. **Add rate limiting (optional):**
   ```bash
   pip install Flask-Limiter
   ```

   ```python
   from flask_limiter import Limiter

   limiter = Limiter(
       app=app,
       key_func=lambda: request.remote_addr,
       default_limits=["100 per hour"]
   )
   ```

---

## 🔧 Common Issues

### Issue 1: "Address already in use"
**Solution:** Change port in `app.py`:
```python
app.run(host='0.0.0.0', port=5002, debug=False, threaded=True)
```

### Issue 2: Sessions lost on deployment
**Problem:** In-memory sessions don't persist on cloud
**Solution:** Add Redis or database session storage (future enhancement)

### Issue 3: Cold starts on free tier
**Problem:** Render free tier sleeps after 15min
**Solution:**
- Upgrade to paid tier, or
- Use Railway (doesn't sleep), or
- Accept cold start delay

### Issue 4: CORS errors
**Problem:** Browser blocks cross-origin requests
**Solution:** Already handled by `CORS(app)` in `app.py`

---

## 📊 Cost Comparison

| Platform | Free Tier | Paid Tier | Best For |
|----------|-----------|-----------|----------|
| **Ngrok** | Limited connections | $8/month (static URL) | Quick demos |
| **Railway** | $5 credit/month | ~$5-10/month | Production |
| **Render** | Free (with sleep) | $7/month (always-on) | Side projects |
| **Google Cloud Run** | 2M requests/month | Pay per use (~$5-20) | Scalable apps |
| **Local Network** | Free | N/A | Testing only |

---

## 🚀 Next Steps

1. Choose deployment method based on your needs
2. Follow setup steps for that option
3. Test deployment with sample inputs
4. Share URL with your audience!

For questions or issues, refer to platform-specific documentation:
- Railway: https://docs.railway.app
- Render: https://render.com/docs
- Google Cloud: https://cloud.google.com/run/docs
- Ngrok: https://ngrok.com/docs
