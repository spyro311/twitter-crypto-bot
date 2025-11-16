
# twitter-crypto-bot

Auto-reply + Auto-like Twitter bot (ChatGPT-powered) configured for large influencer list.

## What this package contains
- `bot.py` : Main bot script (do not commit your .env)
- `requirements.txt`
- `Procfile` : For Railway/Render worker deployment
- `state.json` : created at runtime to persist counters (not included in repo)

## Before deploying
1. Create a GitHub repo and upload these files (do NOT upload a `.env` file).
2. On Railway or Render add the following environment variables:
   - API_KEY
   - API_SECRET
   - ACCESS_TOKEN
   - ACCESS_SECRET
   - OPENAI_API_KEY

## Adjust behavior
Modify the top of `bot.py` to tune:
- DAILY_REPLY_GOAL, DAILY_LIKE_GOAL
- PER_15MIN_REPLY_LIMIT, PER_15MIN_LIKE_LIMIT
- TWEETS_PER_USER_PER_CYCLE

## Important notes on safety and terms
- High-volume automated activity can violate platform rules (X/Twitter). Use conservative rate limits and monitor the account.
- This project includes rate-limit safeguards, but you should adjust them to match your account history and API access tier.
- Do NOT use this bot to spam or harass.

## Deployment
- Railway: Create project > Deploy from GitHub > Add env variables > Railway will detect Procfile and run the worker.
- Render: Create new "Background Worker" or "Web Service" with start command `python bot.py` and add env variables.

