#!/usr/bin/env python3
"""
generate_feed.py

Generates an RSS 2.0 feed (feed.xml) from https://easconsultinggroup.com/eas-blog/

Date strategy (in priority order):
1) Try to parse an explicit full date from the listing page near each post title:
   - "Mar 9, 2023" or "September 18, 2025"
2) If missing, try to extract from the post page:
   - <meta property="article:published_time" content="...">
   - JSON-LD "datePublished"
   - <time datetime="...">
3) If still missing, fall back to an ASSUMPTION:
   - If the post page contains "Date: January 2026" (month + year only),
     assume the 1st of that month at 00:00:00 UTC.
4) If still nothing, fall back to build time (last resort).

Note: Steps 3 and 4 are assumptions. If you want strict accuracy, remove them.
"""

import re
import html
import json
from datetime import datetime, timezone
from urllib.request import Request, urlopen

BLOG_URL = "https://easconsultinggroup.com/eas-blog/"
MAX_ITEMS = 30

USER_AGENT = "Mozilla/5.0 (RSS generator; GitHub Pages)"


def fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def rfc2822(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_full_date_to_dt(date_text: str) -> datetime | None:
    """
    Accepts:
      - 'Mar 9, 2023'
      - 'September 18, 2025'
    Returns UTC datetime at 00:00:00, or None if unparsable.
    """
    s = " ".join(date_text.strip().split())
    fmts = ["%b %d, %Y", "%B %d, %Y"]
    for fmt in fmts:
        try:
            d = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            # normalize time to midnight UTC
            return d.replace(hour=0, minute=0, second=0, microsecond=0)
        except ValueError:
            pass
    return None


def parse_month_year_to_dt(month_year_text: str) -> datetime | None:
    """
    Accepts:
      - 'January 2026'
      - 'Sep 2025'
    ASSUMPTION: returns first day of month at 00:00:00 UTC.
    """
    s = " ".join(month_year_text.strip().split())
    fmts = ["%B %Y", "%b %Y"]
    for fmt in fmts:
        try:
            d = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return d.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        except ValueError:
            pass
    return None


def iso_to_dt(iso_str: str) -> datetime | None:
    """
    Parses ISO strings like:
      - 2025-09-18
      - 2025-09-18T10:22:00Z
      - 2025-09-18T10:22:00+00:00
    """
    s = iso_str.strip()
    s = s.replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        # try date-only
        try:
            d = datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return d
        except Exception:
            return None


def extract_posts_from_listing(listing_html: str) -> list[tuple[str, str, datetime | None]]:
    """
    Extract (title, url, pub_dt_or_none) from listing page.

    It locates:
      <h2 ...><a href="POST_URL">POST_TITLE</a></h2>
    Then looks ahead in nearby text for full dates like:
      'Mar 9, 2023' or 'September 18, 2025'
    """
    h2_link = re.compile(
        r"<h2[^>]*>\s*<a[^>]*href=\"(https://easconsultinggroup\.com/[^\"]+)\"[^>]*>(.*?)</a>\s*</h2>",
        re.IGNORECASE | re.DOTALL,
    )

    # Full dates commonly shown on EAS blog listing pages
    full_date_pat = re.compile(
        r"\b([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}|[A-Z][a-z]+\s+\d{1,2},\s+\d{4})\b"
    )

    posts: list[tuple[str, str, datetime | None]] = []
    seen = set()

    for m in h2_link.finditer(listing_html):
        url = m.group(1).split("#")[0].strip()

        raw_title = m.group(2)
        title = re.sub(r"<[^>]+>", "", raw_title)
        title = html.unescape(re.sub(r"\s+", " ", title)).strip()

        # Skip obvious non-content endpoints
        if url.endswith("/feed/") or url.endswith("/comments/feed/") or "/wp-json/" in url:
            continue
        if url.rstrip("/") == BLOG_URL.rstrip("/"):
            continue

        # Look near the title for a full date string
        window = listing_html[m.end() : m.end() + 1000]
        pub_dt = None
        dm = full_date_pat.search(window)
        if dm:
            pub_dt = parse_full_date_to_dt(dm.group(1))

        key = (title, url)
        if title and key not in seen:
            seen.add(key)
            posts.append((title, url, pub_dt))

    return posts


def try_extract_pub_dt_from_post(post_html: str) -> datetime | None:
    """
    Attempt to extract publish datetime from the post page.

    Priority:
      1) OpenGraph meta article:published_time
      2) JSON-LD datePublished
      3) <time datetime="...">
      4) Text 'Date: January 2026' (ASSUMPTION: first of month)
    """
    # 1) OpenGraph
    m = re.search(
        r'<meta[^>]+property="article:published_time"[^>]+content="([^"]+)"',
        post_html,
        re.IGNORECASE,
    )
    if m:
        dt = iso_to_dt(m.group(1))
        if dt:
            return dt

    m = re.search(
        r'<meta[^>]+name="article:published_time"[^>]+content="([^"]+)"',
        post_html,
        re.IGNORECASE,
    )
    if m:
        dt = iso_to_dt(m.group(1))
        if dt:
            return dt

    # 2) JSON-LD datePublished
    for block in re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        post_html,
        re.DOTALL | re.IGNORECASE,
    ):
        try:
            data = json.loads(block.strip())
            objs = data if isinstance(data, list) else [data]
            for obj in objs:
                if isinstance(obj, dict) and "datePublished" in obj:
                    dt = iso_to_dt(str(obj["datePublished"]))
                    if dt:
                        return dt
        except Exception:
            pass

    # 3) <time datetime="...">
    m = re.search(r'<time[^>]*datetime="([^"]+)"', post_html, re.IGNORECASE)
    if m:
        dt = iso_to_dt(m.group(1))
        if dt:
            return dt

    # 4) Month-year text like "Date: January 2026"
    # ASSUMPTION: first day of that month
    m = re.search(
        r"\bDate:\s*([A-Z][a-z]+)\s+(\d{4})\b",
        post_html,
        re.IGNORECASE,
    )
    if m:
        dt = parse_month_year_to_dt(f"{m.group(1)} {m.group(2)}")
        if dt:
            return dt

    return None


def main() -> int:
    listing_html = fetch(BLOG_URL)
    posts = extract_posts_from_listing(listing_html)[:MAX_ITEMS]

    build_dt = now_utc()

    rss_items: list[str] = []
    for title, link, pub_dt in posts:
        # If listing date missing, try post page extraction
        if pub_dt is None:
            try:
                post_html = fetch(link)
                extracted = try_extract_pub_dt_from_post(post_html)
                if extracted is not None:
                    pub_dt = extracted
            except Exception:
                pass

        # Last-resort assumption: use build time (not accurate, but deterministic)
        if pub_dt is None:
            pub_dt = build_dt

        rss_items.append(
            f"""
    <item>
      <title>{html.escape(title)}</title>
      <link>{html.escape(link)}</link>
      <guid isPermaLink="true">{html.escape(link)}</guid>
      <pubDate>{rfc2822(pub_dt)}</pubDate>
    </item>""".strip()
        )

    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{html.escape("EAS Consulting Group Blog")}</title>
    <link>{html.escape(BLOG_URL)}</link>
    <description>{html.escape("Unofficial RSS feed generated from the EAS Consulting Group blog page.")}</description>
    <lastBuildDate>{rfc2822(build_dt)}</lastBuildDate>
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
