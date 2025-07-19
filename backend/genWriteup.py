import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")

client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL
)

def generate_writeup_for_emotion(emotion, comments):
    if not comments:
        raise ValueError(f"No comments provided for emotion: {emotion}")

    sample_comments = comments[:10]
    comments_text = "\n".join(f"- {c}" for c in sample_comments)

    prompt = f"""
You are a professional marketing writer analyzing online user discussions. Your job is to process the following real user comments expressing the emotion "{emotion}" and create:

1. Three compelling, marketable **headings** summarizing major ideas or topics.
2. Three elaborative **subheadings** that add context to the above.
3. Three representative **quotes** directly from the user comments that reflect the emotion and its key points.

Use this exact format (no extra explanation):

Headings:
- Heading 1
- Heading 2
- Heading 3

Subheadings:
- Subheading 1
- Subheading 2
- Subheading 3

Quotes:
- Quote 1
- Quote 2
- Quote 3

Comments:
{comments_text}
"""

    try:
        response = client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        text = response.choices[0].message.content

        result = {"headings": [], "subheadings": [], "quotes": []}
        current = None

        for line in text.splitlines():
            line = line.strip()
            if line.lower().startswith("headings"):
                current = "headings"
            elif line.lower().startswith("subheadings"):
                current = "subheadings"
            elif line.lower().startswith("quotes"):
                current = "quotes"
            elif line.startswith("-") and current:
                result[current].append(line[1:].strip())

        return result

    except Exception as e:
        print("❌ Error in generate_writeup_for_emotion:", e)
        raise
