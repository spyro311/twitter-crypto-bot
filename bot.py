#!/usr/bin/env python3
"""
twitter-crypto-bot: Auto-reply + Auto-like bot (human-like) ready for deployment.

IMPORTANT:
- Do NOT commit your .env to GitHub.
- Set environment variables on Railway/Render:
  API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET, OPENAI_API_KEY

This bot:
- Replies in short human-like style using OpenAI
- Randomized timing across 24h
- Targets a daily goal of replies and likes
- Persists state to state.json to avoid duplicates across restarts
- Includes conservative rate-limit safeguards (adjust as needed)

USAGE:
- Deploy to Railway/Render as a worker with Procfile: "worker: python bot.py"
"""

import os
import time
import random
import json
import logging
from datetime import datetime, timedelta

import tweepy
from openai import OpenAI

# --------- CONFIG ----------

TARGET_USERS = [
    "web3stripe",
    "UziCryptoo",
    "_Juliaweb3",
    "Cryptosaga001",
    "NebOnChain",
    "TimHaldorsson",
    "Jake_Stott",
    "Joepcxc",
    "iamcandyivie",
    "SimonnWeb3",
    "DinhtienSol",
    "CaoMinhWeb3",
    "banditxbt",
    "R2D2zen",
    "creativeburne",
    "RiddlerNFT",
    "73lV_",
    "holly_web3",
    "thegaboeth",
    "Jampzey",
    "thegreatola",
    "0xbigm7",
    "DRPC777",
    "zaimiriQ",
    "_Kriptopia",
    "0x0Nova",
    "lilbratel3na",
    "lowadka",
    "m00des",
    "shivst3r",
    "what3verman",
    "0xRory"
]

# Daily activity goals (configurable)
DAILY_REPLY_GOAL = 200
DAILY_LIKE_GOAL = 100

# Safety limits (per 15-minute window)
PER_15MIN_REPLY_LIMIT = 50   # adjustable; be careful with high values
PER_15MIN_LIKE_LIMIT = 40

# How many recent tweets to fetch per influencer per cycle
TWEETS_PER_USER_PER_CYCLE = 5

# State file to persist replied/liked ids and counters
STATE_FILE = "state.json"

# OpenAI model & prompt tuning
OPENAI_MODEL = "gpt-4o-mini"  # replace if you prefer another model
SYSTEM_PROMPT = (
    "You are a real human crypto enthusiast tweeting from your personal account.\n"
    "- Reply in 1 or 2 short lines max. Keep it casual, not perfect grammar.\n"
    "- No 'As an AI' or formal disclaimers. No excessive emojis.\n"
    "- If the tweet is technical, respond technically; if it's funny, be funny.\n"
    "- Keep replies varied and human-like (slang/small typos allowed)."
)

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# --------- HELPERS ----------

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    else:
        return {
            "replied_ids": [],
            "liked_ids": [],
            "last_reset": datetime.utcnow().isoformat(),
            "daily_replies": 0,
            "daily_likes": 0,
            "windows": []
        }

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def reset_daily_if_needed(state):
    last_reset = datetime.fromisoformat(state.get("last_reset"))
    if datetime.utcnow().date() != last_reset.date():
        logging.info("New UTC day detected — resetting daily counters.")
        state["daily_replies"] = 0
        state["daily_likes"] = 0
        state["last_reset"] = datetime.utcnow().isoformat()
        state["windows"] = []
        save_state(state)

def record_action_window(state, kind, count):
    # stores per-15-min windows in state["windows"] for simple rate limiting
    now = datetime.utcnow()
    window = { "ts": now.isoformat(), "kind": kind, "count": count }
    state.setdefault("windows", []).append(window)
    # prune old windows beyond 1 day
    cutoff = now - timedelta(days=1)
    state["windows"] = [w for w in state["windows"] if datetime.fromisoformat(w["ts"]) > cutoff]

def actions_in_recent_window(state, kind, minutes=15):
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)
    total = 0
    for w in state.get("windows", []):
        if w["kind"] == kind and datetime.fromisoformat(w["ts"]) >= cutoff:
            total += w["count"]
    return total

# --------- AUTH ----------

def create_clients():
    API_KEY = os.getenv("API_KEY")
    API_SECRET = os.getenv("API_SECRET")
    ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
    ACCESS_SECRET = os.getenv("ACCESS_SECRET")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

    assert API_KEY and API_SECRET and ACCESS_TOKEN and ACCESS_SECRET and OPENAI_API_KEY, "Missing one or more required environment variables."

    # Tweepy (OAuth1 for v1.1 endpoints used here)
    auth = tweepy.OAuthHandler(API_KEY, API_SECRET)
    auth.set_access_token(ACCESS_TOKEN, ACCESS_SECRET)
    api = tweepy.API(auth, wait_on_rate_limit=True)

    # OpenAI client
    openai_client = OpenAI(api_key=OPENAI_API_KEY)

    return api, openai_client

# --------- OPENAI USAGE ----------

def generate_human_reply(openai_client, tweet_text):
    # Keep prompt short; ask for a single short reply
    try:
        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                { "role": "system", "content": SYSTEM_PROMPT },
                { "role": "user", "content": f"Reply to this tweet in 1 short line: \\n\\n{tweet_text}" }
            ],
            max_tokens=60,
            temperature=0.8,
            top_p=0.9
        )
        reply = response.choices[0].message.content.strip()
        # Ensure it's short; if too long, truncate to first line
        reply = reply.splitlines()[0]
        if len(reply) > 280:
            reply = reply[:277] + "..."
        return reply
    except Exception as e:
        logging.exception("OpenAI generation failed: %s", e)
        return None

# --------- BOT LOGIC ----------

def main_loop():
    api, openai_client = create_clients()
    state = load_state()
    reset_daily_if_needed(state)

    logging.info("Bot started. Targets: %d replies/day, %d likes/day", DAILY_REPLY_GOAL, DAILY_LIKE_GOAL)

    while True:
        try:
            reset_daily_if_needed(state)

            # Simple round-robin over influencers
            users = TARGET_USERS.copy()
            random.shuffle(users)

            for user in users:
                # Check if daily goals met
                if state["daily_replies"] >= DAILY_REPLY_GOAL and state["daily_likes"] >= DAILY_LIKE_GOAL:
                    logging.info("Daily goals reached. Sleeping for 30 minutes.")
                    save_state(state)
                    time.sleep(30 * 60)
                    continue

                # Rate-limiting: ensure we don't exceed per-15-min windows
                recent_replies = actions_in_recent_window(state, "reply", minutes=15)
                recent_likes = actions_in_recent_window(state, "like", minutes=15)

                if recent_replies >= PER_15MIN_REPLY_LIMIT or recent_likes >= PER_15MIN_LIKE_LIMIT:
                    # sleep a bit if we've hit short-term limits
                    logging.info("Short-term limit reached (replies=%d likes=%d). Sleeping 5-10 minutes.", recent_replies, recent_likes)
                    time.sleep(random.randint(300, 600))
                    continue

                # Fetch recent tweets
                try:
                    tweets = api.user_timeline(screen_name=user, count=TWEETS_PER_USER_PER_CYCLE, tweet_mode="extended")
                except Exception as e:
                    logging.warning("Failed fetching tweets for %s: %s", user, e)
                    time.sleep(5)
                    continue

                for tweet in tweets:
                    # Skip retweets and replies
                    if hasattr(tweet, "retweeted_status") or tweet.full_text.startswith("RT "):
                        continue

                    tid = str(tweet.id)
                    if tid in state.get("replied_ids", []) and tid in state.get("liked_ids", []):
                        continue

                    # Decide probabilistically whether to like / reply to make behavior human-like
                    will_like = False
                    will_reply = False

                    # Increase probability if under daily goals
                    replies_left = max(0, DAILY_REPLY_GOAL - state["daily_replies"])
                    likes_left = max(0, DAILY_LIKE_GOAL - state["daily_likes"])

                    # Heuristics: if many replies left, higher chance; ensure not always replying
                    p_reply = min(0.9, 0.6 * (replies_left / max(1, len(users)*5)) )
                    p_like = min(0.9, 0.5 * (likes_left / max(1, len(users)*5)) )

                    # Random decision
                    will_reply = random.random() < p_reply
                    will_like = random.random() < p_like

                    # Throttle: never reply & like the same tweet more than once
                    if will_reply and tid in state.get("replied_ids", []):
                        will_reply = False
                    if will_like and tid in state.get("liked_ids", []):
                        will_like = False

                    # Perform like
                    if will_like and state["daily_likes"] < DAILY_LIKE_GOAL:
                        try:
                            api.create_favorite(tweet.id)
                            logging.info("Liked tweet %s from %s", tid, user)
                            state.setdefault("liked_ids", []).append(tid)
                            state["daily_likes"] += 1
                            record_action_window(state, "like", 1)
                            save_state(state)
                            # small human-like pause after like
                            time.sleep(random.uniform(2, 6))
                        except Exception as e:
                            logging.warning("Failed to like %s: %s", tid, e)

                    # Perform reply
                    if will_reply and state["daily_replies"] < DAILY_REPLY_GOAL:
                        reply_text = generate_human_reply(openai_client, tweet.full_text)
                        if reply_text:
                            # sometimes prepend a short opener for variety
                            openers = ["Nice.", "Solid.", "Noted.", "Hmm.", "True.", ""]
                            opener = random.choice(openers)
                            final_reply = (opener + " " + reply_text).strip()
                            # ensure not mentioning the same user twice (we will reply with @username)
                            try:
                                api.update_status(status=f"@{tweet.user.screen_name} {final_reply}", in_reply_to_status_id=tweet.id)
                                logging.info("Replied to %s: %s", tid, final_reply)
                                state.setdefault("replied_ids", []).append(tid)
                                state["daily_replies"] += 1
                                record_action_window(state, "reply", 1)
                                save_state(state)
                                # human-like delay after replying
                                time.sleep(random.uniform(20, 120))
                            except Exception as e:
                                logging.warning("Failed to reply %s: %s", tid, e)

                    # Slight delay between processing tweets
                    time.sleep(random.uniform(1.5, 3.5))

                # after each user, small random pause
                time.sleep(random.uniform(5, 30))

            # End of cycle: small random sleep before next round
            save_state(state)
            # Jitter to make 24-hour spread: sleep between 30s and 5 minutes
            time.sleep(random.uniform(30, 300))

        except KeyboardInterrupt:
            logging.info("KeyboardInterrupt received. Exiting.")
            save_state(state)
            break
        except Exception as e:
            logging.exception("Unhandled error in main loop: %s", e)
            # wait then continue
            time.sleep(30)

if __name__ == "__main__":
    main_loop()
