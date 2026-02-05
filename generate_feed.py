import re
import sys
import html
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

BLOG_URL = "https://easconsultinggroup.com/eas-blog/"
FEED_URL_PLACEHOLDER = "https://YOUR_GITHUB_USERNAME.github.io/eas-blog-rss/feed.xml"

def fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (RSS generator)"})
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")

def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")

def main() -> int:
    html_text = fetch(BLOG_URL)

    # Heuristic link extraction: find blog post links that look like WordPress-style permalinks
    # You may need to tweak this if their HTML structure differs.
    links = re.findall(r'href="(https://easconsultinggroup\.com/[^"]+)"', html_text)
    # Filter likely posts (exclude obvious nav / assets)
    candidates = []
    for link in links:
        if any(x in link for x in ["/wp-content/", "/category/", "/tag/", "#", "mailto:"]):
            continue
        if link.rstrip("/") == BLOG_URL.rstrip("/"):
            continue
        candidates.append(link.split("#")[0])

    # De-duplicate, preserve order
    seen = set()
    ordered = []
    for l in candidates:
        if l not in seen:
            seen.add(l)
            ordered.append(l)

    # Keep first N items
    ordered = ordered[:20]

    # For each post URL, try to fetch title from its <title> tag (simple + robust enough)
    items = []
    for url in ordered:
        try:
            post_html = fetch(url)
            m = re.search(r"<title>(.*?)</title>", post_html, flags=re.IGNORECASE | re.DOTALL)
            title = m.group(1).strip() if m else url
            title = re.sub(r"\s+", " ", title)
            # Often titles include site name like "Post Title - EAS Consulting Group"
            title = title.replace("&#8211;", "-")
            items.append((title, url))
        except Exception:
            continue

    # Build RSS 2.0
    now_rfc2822 = iso_now()
    channel_title = "EAS Consulting Group Blog"
    channel_link = BLOG_URL
    channel_desc = "Unofficial RSS feed generated from the EAS Consulting Group blog page."

    rss_items = []
    for title, link in items:
        safe_title = html.escape(title)
        safe_link = html.escape(link)
        guid = safe_link
        rss_items.append(f"""
        <item>
          <title>{safe_title}</title>
          <link>{safe_link}</link>
          <guid isPermaLink="true">{guid}</guid>
          <pubDate>{now_rfc2822}</pubDate>
        </item>""".strip())

    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{html.escape(channel_title)}</title>
    <link>{html.escape(channel_link)}</link>
    <description>{html.escape(channel_desc)}</description>
    <lastBuildDate>{now_rfc2822}</lastBuildDate>
    {chr(10).join(rss_items)}
  </channel>
</rss>
"""

    with open("feed.xml", "w", encoding="utf-8") as f:
        f.write(rss)

    print(f"Wrote feed.xml with {len(items)} items")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
