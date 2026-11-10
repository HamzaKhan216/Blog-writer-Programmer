import os
import re
import ast
import json
import html
import random
import smtplib
import sys
import time
import requests
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- CONFIGURATION & SECRETS ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
UNSPLASH_CLIENT_ID = os.getenv("UNSPLASH_CLIENT_ID")  # optional for this niche
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")  # App Password
BLOGGER_EMAIL = os.getenv("BLOGGER_EMAIL")

REQUEST_TIMEOUT = 20
MAX_WRITE_ATTEMPTS = 3  # rewrite attempts if the generated Python doesn't parse
BASE_DIR = Path(__file__).parent
TOPICS_FILE = BASE_DIR / "topics.json"
PUBLISHED_FILE = BASE_DIR / "published.json"

BLOG_NAME = "Python Automation for Beginners"
PILLARS = [
    "Excel automation", "PDF automation", "File automation", "Web scraping",
    "Email automation", "Google Sheets automation", "AI scripts",
    "Python errors", "AI coding tools", "JavaScript and React errors",
]


# --- LLM ---
def clean_json_response(text):
    """Removes markdown backticks from LLM responses."""
    text = text.strip()
    if text.startswith("```json"): text = text[7:]
    elif text.startswith("```"): text = text[3:]
    if text.endswith("```"): text = text[:-3]
    return json.loads(text.strip())


def call_llm(system_prompt, user_prompt, max_attempts=4, initial_backoff=1):
    """Attempts Gemini first, falls back to Groq if all retries are exhausted."""
    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent?key={GEMINI_API_KEY}"
    gemini_payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }

    for attempt in range(1, max_attempts + 1):
        try:
            print(f"Gemini attempt {attempt}/{max_attempts}...")
            res = requests.post(gemini_url, json=gemini_payload, headers={"Content-Type": "application/json"}, timeout=REQUEST_TIMEOUT * 3)
            res.raise_for_status()
            response_text = res.json()['candidates'][0]['content']['parts'][0]['text']
            return clean_json_response(response_text)
        except Exception as exc:
            if attempt == max_attempts:
                print(f"Gemini failed after {max_attempts} attempts. Switching to Groq...")
            else:
                backoff = initial_backoff * (2 ** (attempt - 1))
                print(f"Gemini attempt {attempt} failed: {exc}. Retrying in {backoff} seconds...")
                time.sleep(backoff)

    groq_headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    groq_payload = {
        "model": "openai/gpt-oss-120b",
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    }

    for attempt in range(1, max_attempts + 1):
        try:
            print(f"Groq attempt {attempt}/{max_attempts}...")
            res = requests.post("https://api.groq.com/openai/v1/chat/completions", json=groq_payload, headers=groq_headers, timeout=REQUEST_TIMEOUT * 3)
            res.raise_for_status()
            response_text = res.json()['choices'][0]['message']['content']
            return clean_json_response(response_text)
        except Exception as exc:
            if attempt == max_attempts:
                print(f"Groq failed after {max_attempts} attempts.")
                raise
            backoff = initial_backoff * (2 ** (attempt - 1))
            print(f"Groq attempt {attempt} failed: {exc}. Retrying in {backoff} seconds...")
            time.sleep(backoff)


# --- TOPIC QUEUE ---
def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def get_next_topic():
    """Next unpublished topic from topics.json; if the list is used up, ask the LLM for a new one."""
    topics = load_json(TOPICS_FILE, [])
    published = load_json(PUBLISHED_FILE, [])
    done = {p["topic"].lower() for p in published}

    for t in topics:
        if t["title"].lower() not in done:
            return t

    print("Topic list exhausted. Generating a new topic...")
    pillar = random.choice(PILLARS)
    recent = [p["topic"] for p in published][-40:]
    res = call_llm(
        f"You are an SEO strategist for a beginner-friendly coding tutorial blog called '{BLOG_NAME}'.",
        f"""Suggest ONE new, very specific, problem-solving tutorial topic in the category: {pillar}.
It must be a narrow task or exact error people search for (e.g. "How to merge 100 Excel files with Python"),
NOT a broad topic like "Learn Python" or "Best programming language".
Do not repeat or closely overlap any of these: {recent}
Return ONLY JSON: {{"title": "...", "category": "{pillar}"}}"""
    )
    return {"title": res["title"], "category": res.get("category", pillar)}


# --- RESEARCH: verify real libraries instead of Wikipedia ---
def get_package_facts(pip_packages, npm_packages):
    """Looks up each library on PyPI/npm so the writer uses real, current package info."""
    lines = []
    for pkg in (pip_packages or [])[:5]:
        try:
            r = requests.get(f"https://pypi.org/pypi/{pkg}/json", timeout=REQUEST_TIMEOUT)
            if r.status_code == 404:
                lines.append(f"- {pkg}: NOT FOUND on PyPI. Do NOT use it.")
                continue
            r.raise_for_status()
            info = r.json()["info"]
            lines.append(f"- {pkg} (PyPI) latest version {info['version']}, requires Python {info.get('requires_python') or 'unspecified'}: {info.get('summary', '')}")
        except Exception as e:
            print(f"PyPI lookup for '{pkg}' failed: {e}")
    for pkg in (npm_packages or [])[:5]:
        try:
            r = requests.get(f"https://registry.npmjs.org/{pkg}/latest", timeout=REQUEST_TIMEOUT)
            if r.status_code == 404:
                lines.append(f"- {pkg}: NOT FOUND on npm. Do NOT use it.")
                continue
            r.raise_for_status()
            d = r.json()
            lines.append(f"- {pkg} (npm) latest version {d.get('version')}: {d.get('description', '')}")
        except Exception as e:
            print(f"npm lookup for '{pkg}' failed: {e}")
    return "\n".join(lines) if lines else "No third-party libraries needed. Use the standard library only."


def get_unsplash_image(query):
    """Optional hero image. Returns None if unavailable (no more broken placeholder URLs)."""
    if not UNSPLASH_CLIENT_ID:
        return None
    try:
        params = {"query": query, "orientation": "landscape", "per_page": 1, "client_id": UNSPLASH_CLIENT_ID}
        res = requests.get("https://api.unsplash.com/search/photos", params=params, timeout=REQUEST_TIMEOUT)
        data = res.json()
        if data.get("results"):
            return {"url": data["results"][0]["urls"]["regular"], "credit": data["results"][0]["user"]["name"]}
    except Exception as e:
        print(f"Unsplash failed: {e}")
    return None


# --- CODE VALIDATION ---
def find_python_errors(content):
    """Parses every <pre><code class="language-python"> block. Returns a list of syntax errors."""
    errors = []
    blocks = re.findall(r'<pre[^>]*>\s*<code[^>]*language-python[^>]*>(.*?)</code>\s*</pre>', content, flags=re.DOTALL | re.IGNORECASE)
    if not blocks and "python" in content.lower():
        errors.append("No <code class=\"language-python\"> blocks found. Python code must be in <pre><code class=\"language-python\">.")
    for i, block in enumerate(blocks, 1):
        code = html.unescape(re.sub(r"<[^>]+>", "", block))
        try:
            ast.parse(code)
        except SyntaxError as e:
            errors.append(f"Python block {i}: SyntaxError line {e.lineno}: {e.msg}")
    return errors


# --- PUBLISH ---
def publish_to_blogger(title, html_content):
    print("Publishing to Blogger via Email...")
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = BLOGGER_EMAIL
    msg['Subject'] = title
    msg.attach(MIMEText(html_content, 'html'))

    server = smtplib.SMTP('smtp.gmail.com', 587, timeout=REQUEST_TIMEOUT)
    server.starttls()
    server.login(SENDER_EMAIL, SENDER_PASSWORD)
    server.send_message(msg)
    server.quit()
    print("Successfully Published!")


def main():
    # 1. Topic
    topic = get_next_topic()
    print(f"Selected topic: {topic['title']} ({topic['category']})")

    # 2. Strategy
    system_prompt_strategy = (
        f"You are a senior developer and technical writer running '{BLOG_NAME}'. "
        "Positioning: build real projects and automate boring work with Python, JavaScript, and AI."
    )
    user_prompt_strategy = f"""
    Topic: {topic['title']}
    Category: {topic['category']}

    Plan the tutorial. Rules:
    1. Pick a specific long-tail target_keyword matching how beginners search for this exact task or error.
    2. List ONLY third-party libraries the solution truly needs. Never list standard-library modules (os, json, smtplib, sqlite3...). Use well-maintained, real libraries only.
    3. Never invent libraries or functions.

    Return ONLY valid JSON: {{"title": "SEO title under 65 chars", "target_keyword": "...", "seo_keywords": "5 long tail keywords", "pip_packages": ["..."], "npm_packages": ["..."], "image_query": "visual term like 'laptop code'", "angle": "one sentence on what the reader gets"}}
    """
    strategy = call_llm(system_prompt_strategy, user_prompt_strategy)

    # 3. Research: verify libraries
    facts = get_package_facts(strategy.get("pip_packages"), strategy.get("npm_packages"))
    image = get_unsplash_image(strategy.get("image_query", "laptop code"))
    image_html = (
        f'<img src="{image["url"]}" alt="{strategy["target_keyword"]}"/>\n<p>Photo by {image["credit"]} on Unsplash</p>'
        if image else ""
    )

    # 4. Writing, with a syntax check and rewrite loop
    system_prompt_writer = (
        f"You are a senior developer and technical writer for '{BLOG_NAME}'. "
        "Audience: beginners and non-developers who search for an exact task or error and want working code they can "
        "copy, run, and understand in under 10 minutes. Tone: friendly, practical, confident, never hype-y. "
        "Short paragraphs, plain English, no filler intros, no vague theory."
    )
    user_prompt_writer = f"""
    Write a tutorial blog post.
    TITLE: {strategy['title']}
    TARGET KEYWORD: {strategy['target_keyword']}
    SEO KEYWORDS (weave naturally into headers and intro): {strategy.get('seo_keywords', '')}
    ANGLE: {strategy.get('angle', '')}
    VERIFIED LIBRARIES (use only these plus the standard library):
    {facts}

    STRUCTURE (follow exactly, use <h2> for each section):
    1. Intro: 2-3 sentences stating the problem and the result. {image_html and "Put this at the very top first:" } {image_html}
    2. Quick answer: the complete working code (or the fix) right away.
    3. Requirements: Python (or Node) version, pip/npm install command, any sample files needed.
    4. Step-by-step walkthrough: explain each part of the code in plain language.
    5. Expected output: show what running it prints or produces.
    6. Common errors: real error messages with the fix for each.
    7. Variations: 2-3 ways to extend it.
    8. FAQ: 3-4 short questions people actually search.

    CODE RULES (critical):
    - Every Python block must be complete, runnable, commented, and valid syntax, wrapped as <pre><code class="language-python">...</code></pre>.
    - Use class="language-bash" for terminal commands, class="language-javascript" for JS, class="language-text" for output and error messages.
    - HTML-escape code (&lt; &gt; &amp;).
    - If you are unsure a function or API exists, use a simpler approach you are certain about.
    - Never fabricate outputs, statistics, screenshots, or sources.

    STYLE RULES:
    - Never use em-dashes. Avoid 'Moreover,', 'In today's world,' and 'It is important to note'.
    - Use <h2>, <h3>, <p>, <ul>, <ol>, <pre>, <code>. Do NOT add <h1>, <html>, or <body>.
    - 900-1300 words excluding code.

    Return ONLY JSON: {{"title": "{strategy['title']}", "content": "...HTML..."}}
    """

    post, errors = None, []
    for attempt in range(1, MAX_WRITE_ATTEMPTS + 1):
        prompt = user_prompt_writer
        if errors:
            prompt += "\n\nYOUR PREVIOUS DRAFT FAILED VALIDATION. Fix these and rewrite the whole post:\n" + "\n".join(errors)
        post = call_llm(system_prompt_writer, prompt)
        if not post.get('content') or len(post['content']) < 100:
            errors = ["Content too short or empty."]
            continue
        errors = find_python_errors(post['content'])
        if not errors:
            break
        print(f"Validation attempt {attempt} failed: {errors}")

    if errors:
        print("ERROR: could not produce valid code. Not publishing.")
        sys.exit(1)

    post['content'] = post['content'].replace("\u2014", "-")

    # 5. Publish and record
    publish_to_blogger(post['title'], post['content'])
    published = load_json(PUBLISHED_FILE, [])
    published.append({"topic": topic['title'], "title": post['title']})
    PUBLISHED_FILE.write_text(json.dumps(published, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
