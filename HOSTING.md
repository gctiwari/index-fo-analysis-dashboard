# Hosting This App for Free — Step by Step

## The honest picture first

GitHub itself only hosts *static* files (HTML/CSS/JS) via GitHub Pages — it
cannot run a Python server, a scheduler, or a database. So "host on GitHub"
in practice means: **your code lives on GitHub, and two other free
services deploy it automatically whenever you push.** That's the standard,
free way most small projects go live today. No credit card required for
any of the steps below.

The combo:
- **GitHub** — where your code lives (also what triggers deployments)
- **Render** (free tier) — runs the Python backend (FastAPI + the scheduler)
- **Vercel** (free tier, forever) — runs the Next.js frontend

**Two real limitations of the free tier you should know before you start**
(this app specifically needs an always-on server + a database, which is
exactly what free tiers are weakest at):

1. **Render's free web service falls asleep after 15 minutes with no
   traffic**, and takes 30-60 seconds to "wake up" on the next request.
   That also means the 09:16 / every-3-min / 15:32 scheduler jobs **won't
   fire reliably** if the server is asleep. Fix: use a free uptime pinger
   (step 6 below) to keep it awake during market hours, or just use the
   "Generate now / Check now / Finalize day" buttons in the UI manually.
2. **Render's free web service has no persistent disk.** Every time it
   redeploys or restarts (including waking from sleep, sometimes), the
   SQLite database (`tracking.db`) — your paper-trade history — **resets**.
   For a demo this is fine. For real historical tracking you'd want
   Render's paid $7/month instance with a persistent disk, or point
   `DATABASE_URL` at a free-tier managed Postgres elsewhere. This is a
   genuine trade-off of free hosting, not a bug in the app.

If you just want to show off the dashboards and don't care about
long-term trade history surviving server restarts, the free tier is fine.

---

## Step 1 — Put the code on GitHub

1. Install Git if you don't have it: https://git-scm.com/downloads
2. Go to https://github.com, sign in (or create a free account), click the
   **+** in the top right → **New repository**. Name it e.g.
   `index-fo-analysis-dashboard`, leave it Public or Private, don't add a
   README (you already have one), click **Create repository**.
3. On your computer, open a terminal in the `trading-dashboard` folder
   (the one with `backend/` and `frontend/` inside it) and run:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/YOUR-USERNAME/index-fo-analysis-dashboard.git
   git push -u origin main
   ```
   Replace `YOUR-USERNAME` with your actual GitHub username. GitHub will
   prompt you to sign in the first time you push.
4. Refresh the GitHub page — you should see all your files there.

---

## Step 2 — Deploy the backend on Render

1. Go to https://render.com → **Get Started** → sign up with GitHub (this
   also grants Render permission to read your repos).
2. Click **New +** → **Web Service**.
3. Pick your `index-fo-analysis-dashboard` repo from the list, click **Connect**.
4. Fill in the settings:
   - **Name**: `index-fo-analysis-api` (or anything)
   - **Root Directory**: `backend`  ← important, this is a monorepo
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Instance Type**: `Free`
5. Scroll to **Environment Variables** and add:
   - `CORS_ORIGINS` = `http://localhost:3000` (you'll update this in Step 4
     once you know your Vercel URL — leave it as-is for now)
6. Click **Create Web Service**. Render will build and deploy — takes a
   few minutes the first time. When it's done you'll get a URL like:
   ```
   https://index-fo-analysis-api.onrender.com
   ```
   Keep this URL — the frontend needs it. Test it by opening
   `https://index-fo-analysis-api.onrender.com/health` in your browser;
   you should see `{"status":"healthy"}`.

---

## Step 3 — Deploy the frontend on Vercel

1. Go to https://vercel.com → **Sign Up** → **Continue with GitHub**.
2. Click **Add New...** → **Project**.
3. Find your `index-fo-analysis-dashboard` repo, click **Import**.
4. Vercel will ask for the project settings:
   - **Root Directory**: click **Edit**, choose `frontend`  ← important
   - **Framework Preset**: it should auto-detect **Next.js**
5. Expand **Environment Variables** and add:
   - **Name**: `NEXT_PUBLIC_API_URL`
   - **Value**: `https://index-fo-analysis-api.onrender.com/api`
     (your Render URL from Step 2, with `/api` on the end)
6. Click **Deploy**. In a minute or two you'll get a live URL like:
   ```
   https://index-fo-analysis-dashboard.vercel.app
   ```

---

## Step 4 — Connect the two (fix CORS)

Right now the backend only trusts requests from `localhost:3000`, so your
live frontend can't talk to it yet. Fix it:

1. Go back to your **Render** dashboard → your web service → **Environment**.
2. Edit `CORS_ORIGINS` to:
   ```
   http://localhost:3000,https://index-fo-analysis-dashboard.vercel.app
   ```
   (use your actual Vercel URL from Step 3)
3. Save — Render will automatically redeploy with the new setting.
4. Open your Vercel URL in a browser. The dashboard should now load real
   data from your Render backend.

---

## Step 5 — Every future update is automatic

From now on, whenever you want to change something:
```bash
git add .
git commit -m "describe what you changed"
git push
```
Both Render and Vercel are watching your GitHub repo — they'll
automatically rebuild and redeploy within a minute or two of every push.
You don't need to repeat the steps above.

---

## Step 6 (optional) — Keep the backend awake during market hours

Since Render's free tier sleeps after 15 minutes idle, the automatic
09:16 / 3-min / 15:32 scheduler won't run reliably unless something is
"visiting" the server. A free fix:

1. Go to https://uptimerobot.com → free sign-up.
2. **Add New Monitor** → **HTTP(s)** → paste
   `https://index-fo-analysis-api.onrender.com/health` → set the check
   interval to 5 minutes → save.
3. UptimeRobot will now ping your backend every 5 minutes, which keeps it
   from falling asleep during that window. Note: this uses your free
   750-hours/month Render compute allowance faster, but 750 hours already
   covers an entire month running continuously, so this is fine for a
   single free service.

Without this step, the app still works — you'll just need to click
"Generate now / Check now / Finalize day" manually in the Trade Tracker
tab instead of relying on the automatic schedule, and the very first
request after idle time will take 30-60 seconds to respond (cold start).

---

## Quick troubleshooting

- **Frontend loads but shows "Couldn't load this view" everywhere**:
  almost always a CORS or wrong `NEXT_PUBLIC_API_URL` issue — check Step 3
  and 4 again, and open your browser's dev tools (F12) → Network tab to
  see the actual error.
- **Backend works when you visit `/health` but the dashboard is empty**:
  check Render's **Logs** tab for the service — it'll show the same kind
  of yfinance/Yahoo errors you'd see locally, and the fixes are the same
  ones already built into `app/data/fetcher.py`.
- **First request after a while is very slow**: that's the free-tier cold
  start (30-60s) mentioned above — normal, not a bug.
- **Paper-trade history disappeared**: the free Render disk is not
  persistent — see the "honest picture" section at the top.
