from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import requests
import io
import csv
import os
from dotenv import load_dotenv
load_dotenv()
import reddit_scraper
import generate_clusters
import genWriteup
import asyncio



SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_API_KEY")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

app = FastAPI()

# CORS setup (replace "*" with your frontend URL if needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/scrape_comments")
async def scrape_comments_route(request: Request):
    data = await request.json()
    subreddits = data.get("subreddits", [])
    if not subreddits or not isinstance(subreddits, list):
        raise HTTPException(status_code=400, detail="Invalid subreddit list")

    print(f"📥 Subreddits received: {subreddits}")

    try:
        results = await reddit_scraper.scrape_comments_async(subreddits)
    except Exception as e:
        print("❌ Async scraping failed:", str(e))
        raise HTTPException(status_code=500, detail="Failed to scrape comments")

    for name in subreddits:
        if name in results and results[name]:
            returned_comments = results[name][:25]
            print(f"\n✅ Returning 25 comments from: r/{name}")
            for c in returned_comments:
                print(f"- {c['body'][:100]}...")
            return {"subreddit": name, "comments": returned_comments}

    raise HTTPException(status_code=500, detail="No valid subreddits scraped")

@app.get("/comments_by_subreddit")
def comments_by_subreddit(name: str = None):
    if not name:
        raise HTTPException(status_code=400, detail="Missing subreddit name")

    comment_res = requests.get(
        f"{SUPABASE_URL}/rest/v1/comments?subreddit=eq.{name}&limit=25",
        headers=HEADERS
    )

    if comment_res.status_code != 200:
        raise HTTPException(status_code=500, detail="Failed to fetch comments")

    comments = comment_res.json()

    for c in comments:
        c['emotion'] = c.get('emotion', None)

    print(f"\n📤 Returning 25 comments from Supabase for: r/{name}")
    for c in comments:
        print(f"- {c['body'][:100]}...")

    return {"subreddit": name, "comments": comments}

@app.get("/download_all_comments")
def download_all_comments():
    print("📦 Generating CSV download for all comments...")

    response = requests.get(
        f"{SUPABASE_URL}/rest/v1/comments?select=*",
        headers=HEADERS
    )

    if response.status_code != 200:
        print("❌ Failed to fetch comments from Supabase:", response.text)
        raise HTTPException(status_code=500, detail="Failed to fetch comments")

    comments = response.json()
    if not comments:
        print("⚠️ No comments found in the database.")
        raise HTTPException(status_code=404, detail="No comments available for download")

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "id", "post_id", "subreddit", "author", "body", "created_utc",
        "score", "emotion", "parent_id", "permalink"
    ])
    writer.writeheader()
    for c in comments:
        writer.writerow({
            "id": c.get("id"),
            "post_id": c.get("post_id"),
            "subreddit": c.get("subreddit"),
            "author": c.get("author", "N/A"),
            "body": c.get("body", "").replace("\n", " ").strip(),
            "created_utc": c.get("created_utc"),
            "score": c.get("score"),
            "emotion": c.get("emotion", "N/A"),
            "parent_id": c.get("parent_id"),
            "permalink": c.get("permalink")
        })

    output.seek(0)
    return StreamingResponse(
        iter([output.read()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=reddit_comments.csv"
        }
    )

@app.get("/get_emotion_clusters_one")
def get_emotion_clusters_route_one():
    try:
        emotions = generate_clusters.get_emotion_clusters_one()
        return {"clusters": emotions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/get_comments_by_emotion_one")
async def get_comments_by_emotion_route_one(request: Request):
    data = await request.json()
    emotion = data.get("emotion")
    if not emotion:
        raise HTTPException(status_code=400, detail="Missing emotion")

    try:
        comments = generate_clusters.get_comments_for_emotion_one(emotion)
        return {"emotion": emotion, "comments": comments}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_emotion_counts")
def get_emotion_counts_route():
    try:
        counts = generate_clusters.get_emotion_counts()
        return counts
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_emotion_clusters_two")
def get_clusters_two():
    try:
        clusters = generate_clusters.get_emotion_counts()
        return {"clusters": {c["emotion"]: c["count"] for c in clusters}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate_writeup")
async def generate_writeup(request: Request):
    data = await request.json()
    emotion = data.get("emotion")
    if not emotion:
        raise HTTPException(status_code=400, detail="Missing emotion")

    try:
        comments = generate_clusters.get_comments_for_emotion_one(emotion)
        bodies = [c["body"] for c in comments]
        result = genWriteup.generate_writeup_for_emotion(emotion, bodies)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
