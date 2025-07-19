import time
import json
import asyncio
import httpx
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()
import os
print("🔑 REDDIT_CLIENT_ID =", os.getenv("REDDIT_CLIENT_ID"))
import asyncpraw
from openai import OpenAI


# Load .env file from project root (one level up from /backend)



reddit = asyncpraw.Reddit(
    client_id=os.getenv("REDDIT_CLIENT_ID"),
    client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
    user_agent=os.getenv("REDDIT_USER_AGENT"),
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_API_KEY")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

AI_LIMIT = 30
REDDIT_LIMIT = 70
POST_LIMIT = 1
REPLACE_MORE_LIMIT = None  # Fully expand all 'more comments'

ALLOWED_EMOTIONS = [
    "Joy", "Sadness", "Anger", "Fear", "Surprise", "Disgust", "Neutral",
    "Hope", "Frustration", "Humor", "Confusion", "Curiosity", "Amusement",
    "Empathy", "Gratitude", "Relief", "Irony", "Sympathy", "Anticipation", "Interest"
]

ai_call_count = 0
ai_window_start = time.time()
reddit_call_count = 0
reddit_window_start = time.time()

# 🔁 Reusable HTTP clients
supabase_client = httpx.AsyncClient(headers=HEADERS)
openai_client = httpx.AsyncClient()

async def async_guard_ai():
    global ai_call_count, ai_window_start
    now = time.time()
    elapsed = now - ai_window_start
    if elapsed >= 60:
        ai_window_start = now
        ai_call_count = 0
        elapsed = 0
    if ai_call_count >= AI_LIMIT:
        sleep_time = 60 - elapsed
        print(f"🔁 AI limit reached: sleeping {sleep_time:.1f}s...", flush=True)
        await asyncio.sleep(sleep_time)
        ai_window_start = time.time()
        ai_call_count = 0

async def async_guard_reddit(calls=1):
    global reddit_call_count, reddit_window_start
    now = time.time()
    elapsed = now - reddit_window_start
    if elapsed >= 60:
        reddit_window_start = now
        reddit_call_count = 0
        elapsed = 0
    if reddit_call_count + calls > REDDIT_LIMIT:
        sleep_time = 60 - elapsed
        print(f"🔁 Reddit limit reached: sleeping {sleep_time:.1f}s...", flush=True)
        await asyncio.sleep(sleep_time)
        reddit_window_start = time.time()
        reddit_call_count = 0

def utc_to_iso(utc_ts):
    return datetime.utcfromtimestamp(utc_ts).isoformat()

def deduplicate_dicts(records, key):
    seen = set()
    deduped = []
    for r in records:
        val = r[key]
        if val not in seen:
            seen.add(val)
            deduped.append(r)
    return deduped

async def async_bulk_upsert(table: str, records: list):
    if not records:
        return
    resp = await supabase_client.post(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers={"Prefer": "resolution=merge-duplicates"},
        json=records
    )
    if resp.status_code not in (200, 201):
        print(f"❌ Failed to bulk upsert {table}:", resp.text, flush=True)

async def async_upsert_post(post_data):
    await asyncio.gather(
        async_bulk_upsert("subreddits", [{"name": post_data["subreddit"]}]),
        async_bulk_upsert("authors", [{"username": post_data["author"]}])
    )
    resp = await supabase_client.post(
        f"{SUPABASE_URL}/rest/v1/posts",
        headers={"Prefer": "resolution=merge-duplicates"},
        json=post_data
    )
    if resp.status_code not in (200, 201):
        print("❌ Failed to upsert post:", resp.text, flush=True)

async def async_batch_patch_emotions(comments):
    update_data = [{"id": c["id"], "emotion": c["emotion"]} for c in comments if c.get("emotion") is not None]
    if not update_data:
        return
    await async_bulk_upsert("comments", update_data)

async def _openai_async_call(payload: dict) -> dict:
    resp = await openai_client.post(
        f"{os.getenv('OPENAI_BASE_URL', 'https://api.groq.com/openai/v1')}/chat/completions",
        headers={
            "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=60.0
    )
    resp.raise_for_status()
    return resp.json()

async def analyze_emotions_batch_async(comments):
    global ai_call_count
    comment_texts = [f"{i+1}. {c['body']}" for i, c in enumerate(comments)]
    allowed_str = ", ".join(ALLOWED_EMOTIONS)
    prompt = (
        "You will be given a list of Reddit comments, each numbered.\n"
        "For each comment, label it with the SINGLE most appropriate emotion from the following list ONLY:\n"
        f"{allowed_str}\n\n"
        "Respond ONLY in the following format:\n"
        "1. [emotion]\n2. [emotion]\n...\n\n"
        "Here are the comments:\n\n" + "\n\n".join(comment_texts)
    )

    payload = {
        "model": "meta-llama/llama-4-scout-17b-16e-instruct",
        "messages": [
            {"role": "system", "content": "You are an expert at identifying emotions in text."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0,
        "max_tokens": 3000
    }

    try:
        await async_guard_ai()
        result = await _openai_async_call(payload)
        ai_call_count += 1
        raw_output = result["choices"][0]["message"]["content"].strip()
        output = []
        allowed_set = set(e.lower() for e in ALLOWED_EMOTIONS)
        for line in raw_output.split("\n"):
            line = line.strip()
            if not line:
                continue
            if ". " in line:
                emotion = line.split(". ", 1)[1].strip()
            else:
                emotion = line
            output.append(emotion if emotion.lower() in allowed_set else "Unknown")
        return output
    except Exception as e:
        print("❌ OpenAI API error during batch:", e, flush=True)
        return ["Unknown"] * len(comments)

async def scrape_subreddit(sub_name):
    global reddit_call_count
    results = []
    print(f"➡️ Processing subreddit: {sub_name}", flush=True)
    try:
        await async_guard_reddit()
        sub = await reddit.subreddit(sub_name)
        reddit_call_count += 1
        print(f"✅ Subreddit object fetched: {sub_name}", flush=True)
    except Exception as e:
        print(f"❌ Invalid subreddit '{sub_name}': {e}", flush=True)
        return results

    try:
        async for submission in sub.hot(limit=POST_LIMIT):
            print(f"📄 Processing submission: {submission.id} - {submission.title}", flush=True)
            await async_guard_reddit()
            reddit_call_count += 1

            author_name = str(submission.author) if submission.author else "deleted"
            post_data = {
                "id": submission.id,
                "author": author_name,
                "created_utc": utc_to_iso(submission.created_utc),
                "permalink": submission.permalink,
                "score": submission.score,
                "selftext": submission.selftext,
                "subreddit": str(submission.subreddit),
                "title": submission.title,
                "num_comments": submission.num_comments
            }
            await async_upsert_post(post_data)
            print(f"✔️ Upserted post {submission.id}", flush=True)

            await async_guard_reddit()
            comments = await submission.comments()
            await comments.replace_more(limit=REPLACE_MORE_LIMIT)
            comment_list = await comments.list()

            all_comments = []
            for comment in comment_list:
                print(f"🗨️ Found comment {comment.id} by {comment.author}", flush=True)
                comment_author = str(comment.author) if comment.author else "deleted"
                cdata = {
                    "id": comment.id,
                    "post_id": submission.id,
                    "subreddit": sub_name,
                    "author": comment_author,
                    "body": comment.body,
                    "created_utc": utc_to_iso(comment.created_utc),
                    "score": comment.score,
                    "parent_id": comment.parent_id,
                    "permalink": comment.permalink,
                    "sentiment": None,
                    "sentiment_score": None,
                    "readability": None,
                    "hashtag_count": 0,
                    "emotion": None,
                    "clusters": None
                }
                all_comments.append(cdata)

            print(f"📝 Total comments collected for submission {submission.id}: {len(all_comments)}", flush=True)

            unique_subreddits = deduplicate_dicts([{"name": c["subreddit"]} for c in all_comments], "name")
            unique_authors = deduplicate_dicts([{"username": c["author"]} for c in all_comments], "username")

            await async_bulk_upsert("subreddits", unique_subreddits)
            await async_bulk_upsert("authors", unique_authors)
            await async_bulk_upsert("comments", all_comments)

            print(f"✔️ Bulk upserted comments and metadata", flush=True)

            BATCH_SIZE = 50
            batches = [all_comments[i:i + BATCH_SIZE] for i in range(0, len(all_comments), BATCH_SIZE)]
            emotion_tasks = [analyze_emotions_batch_async(batch) for batch in batches]

            print(f"⏳ Starting emotion analysis for {len(all_comments)} comments in {len(batches)} batches", flush=True)
            emotion_results = await asyncio.gather(*emotion_tasks)
            print(f"✅ Completed emotion analysis", flush=True)

            patch_tasks = []
            for batch, emotions in zip(batches, emotion_results):
                for cmt, emo in zip(batch, emotions):
                    cmt["emotion"] = emo
                patch_tasks.append(async_batch_patch_emotions(batch))
            await asyncio.gather(*patch_tasks)

            results = all_comments

    except Exception as e:
        print(f"❌ Error processing subreddit '{sub_name}': {e}", flush=True)

    return results

async def scrape_comments_async(subreddits):
    print(f"📥 Starting scrape for subreddits: {subreddits}", flush=True)
    tasks = [scrape_subreddit(sub_name) for sub_name in subreddits]
    results_list = await asyncio.gather(*tasks)
    results = {sub_name: res for sub_name, res in zip(subreddits, results_list)}
    await supabase_client.aclose()
    await openai_client.aclose()
    await reddit.close()
    print("\n✅ Final scrape results (truncated):", flush=True)
    print(json.dumps(results, indent=2)[:1500], flush=True)
    return results or {}
