import os
import requests

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_API_KEY")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

def get_emotion_clusters_one():
    """
    Returns list of unique emotions found in comments table.
    """
    url = f"{SUPABASE_URL}/rest/v1/comments?select=emotion&emotion=not.is.null&distinct=emotion"
    res = requests.get(url, headers=HEADERS)
    if res.status_code != 200:
        raise Exception(f"Failed to fetch emotion clusters: {res.text}")
    data = res.json()
    # Extract emotions, filter out nulls just in case
    emotions = [item['emotion'] for item in data if item.get('emotion')]
    return emotions

def get_comments_for_emotion_one(emotion, limit=50):
    """
    Returns latest full comment dicts (not just body) for a given emotion.
    """
    url = (
        f"{SUPABASE_URL}/rest/v1/comments"
        f"?select=id,post_id,subreddit,author,body,created_utc,score,emotion"
        f"&emotion=eq.{emotion}"
        f"&order=created_utc.desc&limit={limit}"
    )
    res = requests.get(url, headers=HEADERS)
    if res.status_code != 200:
        raise Exception(f"Failed to fetch comments for emotion {emotion}: {res.text}")
    data = res.json()

    # No need to rename "emotion" field; it already matches frontend expectation
    return data

import os
import requests
from collections import Counter

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_API_KEY")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

def get_emotion_counts():
    """
    Returns a list of {emotion: str, count: int} by fetching
    all non-null emotions and counting them in Python.
    """
    # 1) Fetch all comments with an emotion
    url = (
        f"{SUPABASE_URL}/rest/v1/comments"
        "?select=emotion&emotion=not.is.null"
        "&limit=10000"      # adjust if you have >10k comments
    )
    res = requests.get(url, headers=HEADERS)
    if res.status_code != 200:
        raise Exception(f"Failed to fetch emotion list: {res.status_code} {res.text}")

    data = res.json()
    # 2) Collect only the emotion field
    emotions = [item["emotion"] for item in data if item.get("emotion")]

    # 3) Tally them
    counter = Counter(emotions)

    # 4) Build the list in the format [{emotion, count}, ...]
    return [{"emotion": emo, "count": counter[emo]} for emo in counter]

