# AI Blog Bot: Python Automation for Beginners

Autonomous tutorial generator that publishes to Blogger via email.

## How It Works

1. **Topic** - Takes the next unpublished title from `topics.json`. When the list runs out, the LLM generates new narrow topics in the same pillars.
2. **Strategy** - Gemini (Groq fallback) defines the SEO title, keywords, and the libraries needed.
3. **Research** - Verifies each library on PyPI/npm (real name, latest version, Python requirement).
4. **Writing** - Generates a tutorial: quick answer, requirements, walkthrough, output, common errors, variations, FAQ.
5. **Validation** - Every Python block is parsed with `ast`. Syntax errors trigger a rewrite (up to 3 attempts). If it still fails, nothing is published and the run fails.
6. **Publish** - Emails the post to Blogger, then records it in `published.json`.

## Setup

Same secrets as before: `GROQ_API_KEY`, `GEMINI_API_KEY`, `SENDER_EMAIL`, `SENDER_PASSWORD`, `BLOGGER_EMAIL`. `UNSPLASH_CLIENT_ID` is now optional.

## Notes

- Syntax is checked, not behavior. Run each script yourself before trusting it, or review posts after publishing.
- Mail-to-Blogger can't set labels, search description, or permalink. Set those in Blogger manually.
- Edit `topics.json` to steer topics. Posts already in `published.json` are skipped.
