import re
import html
from datetime import datetime, timezone
from urllib.request import Request, urlopen

BLOG_URL = "https://easconsultinggroup.com/eas-blog/"

def fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (RSS generator)"})
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")

def rfc2822_now() -> str:
    return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")

def extract_posts_from_listing(listing_html: str) -> list[tuple[str, str]]:
    """
    Extract (title, url) pairs from the blog listing page.
    Targets the typical WordPress pattern:
      <h2 ...><a href="POST_URL">POST_TITLE</a></h2>
    """
    pattern = re.compile(
        r"<h2[^>]*>\s*<a[^>]*href=\"(https://easconsultinggroup\.com/[^\"]+)\"[^>]*>(.*?)</a>\s*</h2>",
        re.IGNORECASE | re.DOTALL,
    )

    posts: list[tuple[str, str]] = []
    seen = set()

    for m in pattern.finditer(listing_html):
        url = m.group(1).split("#")[0].strip()
        raw_title = m.group(2)

        # Strip nested tags inside the <a> (if any)
        title = re.sub(r"<[^>]+>", "", raw_title)
        title = html.unescape(re.sub(r"\s+", " ", title)).strip()

        # Exclude obvious non-posts (defensive)
        if url.endswith("/feed/") or url.endswith("/comments/feed/") or "/wp-json/" in url:
            continue
        if url.rstrip("/") == BLOG_URL.rstrip("/"):
            continue

        key = (title, url)
        if key not in seen and title:
            seen.add(key)
            posts.append((title, url))

    return posts

def try_extract_pubdate_from_post(post_html: str) -> str | None:
    """
    Best-effort: some pages expose a machine-readable time tag.
    If not found, return None and we will fall back to now.
    """
    # Common WP patterns
    # <time datetime="2026-01-22T...">...
    m = re.search(r'<time[^>]*datetime="([^"]+)"', post_html, re.IGNORECASE)
    if m:
        dt = m.group(1).strip()
        # Normalize: accept YYYY-MM-DD or ISO datetime
        try:
            if "T" in dt:
                d = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            else:
                d = datetime.fromisoformat(dt).replace(tzinfo=timezone.utc)
            return d.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
        except Exception:
            pass
    return None

def main() -> int:
    listing_html = fetch(BLOG_URL)
    posts = extract_posts_from_listing(listing_html)[:20]

    now_rfc2822 = rfc2822_now()

    rss_items = []
    for title, link in posts:
        pub = now_rfc2822
        try:
            post_html = fetch(link)
            extracted = try_extract_pubdate_from_post(post_html)
            if extracted:
                pub = extracted
        except Exception:
            pass

        rss_items.append(f"""
        <item>
          <title>{html.escape(title)}</title>
          <link>{html.escape(link)}</link>
          <guid isPermaLink="true">{html.escape(link)}</guid>
          <pubDate>{pub}</pubDate>
        </item>""".strip())

    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{html.escape("EAS Consulting Group Blog")}</title>
    <link>{html.escape(BLOG_URL)}</link>
    <description>{html.escape("Unofficial RSS feed generated from the EAS Consulting Group blog page.")}</description>
    <lastBuildDate>{now_rfc2822}</lastBuildDate>
    {chr(10).join(rss_items)}
  </channel>
</rss>
"""

    with open("feed.xml", "w", encoding="utf-8") as f:
        f.write(rss)

    print(f"Wrote feed.xml with {len(posts)} items")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
