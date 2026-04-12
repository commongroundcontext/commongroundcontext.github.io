#!/usr/bin/env python3
"""
Scrapes the latest post from commongroundcontext.com and prepends it
to feed.json and feed.xml.

Posts on the site are plain text separated by underscore dividers — there
are no HTML id attributes. This script locates each post by its heading
text ("Post 11 –– 2026-04-12") and collects the lines that follow.

Exits cleanly (code 0) if the next post is not yet published.
"""

import json
import re
import sys
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

SITE_URL  = "https://commongroundcontext.com/"
FEED_JSON = "feed.json"
FEED_XML  = "feed.xml"


# ── helpers ───────────────────────────────────────────────────────────────────

def get_latest_post_number(feed_data: dict) -> int:
    """Return the highest post number already present in feed.json."""
    max_num = 0
    for item in feed_data.get("items", []):
        m = re.search(r"(\d+)$", item.get("id", ""))
        if m:
            max_num = max(max_num, int(m.group(1)))
    return max_num


def find_post_content(page_text: str, post_num: int):
    """
    Locate the post by matching its heading line, e.g.:
        Post 11 –– 2026-04-12
    Then collect the content lines that follow until the next
    underscore separator or the next post heading.

    Returns (lines, post_date) on success, or (None, None) if not found.
    """
    # Step 1: find "Post 11" (flexible — any leading zeros, case insensitive)
    post_re = re.compile(rf"Post\s+0*{post_num}\b", re.IGNORECASE)
    m = post_re.search(page_text)
    if m is None:
        print(f"  Heading 'Post {post_num}' not found in page text.")
        return None, None

    # Step 2: look for a date (YYYY-MM-DD) within 50 chars of the heading
    window = page_text[m.start(): m.start() + 50]
    date_m = re.search(r"(\d{4}-\d{2}-\d{2})", window)
    if date_m:
        try:
            post_date = datetime.strptime(date_m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            post_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        content_start = m.start() + date_m.end()
    else:
        post_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        content_start = m.end()

    # Collect lines after the heading
    after = page_text[content_start:]
    lines = []
    for line in after.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"_{4,}", stripped):                              # underscore divider
            break
        if re.match(r"Post\s+\d+\s*[-\u2013\u2014]", stripped, re.IGNORECASE):  # next heading
            break
        lines.append(stripped)

    if not lines:
        print("  Found heading but no content lines after it.")
        return None, None

    print(f"  Found {len(lines)} content line(s) for Post {post_num:04d}")
    return lines, post_date


def format_title(post_num: int, post_date: datetime) -> str:
    """'Post 0011 — April 12, 2026'"""
    return (
        f"Post {post_num:04d} \u2014 "
        f"{post_date.strftime('%B')} {post_date.day}, {post_date.year}"
    )


def lines_to_json_html(lines: list) -> str:
    """Single-line <p>text</p> concatenation for JSON Feed."""
    return "".join(f"<p>{line}</p>" for line in lines)


def lines_to_xml_html(lines: list) -> str:
    """One <p>text</p> per line for RSS content:encoded."""
    return "\n".join(f"<p>{line}</p>" for line in lines)


def lines_to_description(lines: list, count: int = 3) -> str:
    """Plain-text snippet of the first N lines for RSS description."""
    return "\n".join(lines[:count])


# ── feed writers ──────────────────────────────────────────────────────────────

def update_feed_json(post_num: int, post_date: datetime, content_html: str) -> None:
    with open(FEED_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    new_item = {
        "id":             f"commonground-post-{post_num:04d}",
        "title":          format_title(post_num, post_date),
        "url":            f"https://commongroundcontext.com/#post{post_num:04d}",
        "date_published": post_date.strftime("%Y-%m-%dT00:00:00Z"),
        "content_html":   content_html,
    }
    data["items"].insert(0, new_item)

    with open(FEED_JSON, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"  {FEED_JSON} updated — prepended {new_item['id']}")


def update_feed_xml(
    post_num: int,
    post_date: datetime,
    content_html_xml: str,
    description_text: str,
) -> None:
    with open(FEED_XML, "r", encoding="utf-8") as f:
        xml = f.read()

    title    = format_title(post_num, post_date)
    url      = f"https://commongroundcontext.com/#post{post_num:04d}"
    guid     = f"commonground-post-{post_num:04d}"
    pub_date = post_date.strftime("%a, %d %b %Y 00:00:00 GMT")

    new_item = (
        f"\n    <item>\n"
        f"      <title>{title}</title>\n"
        f"      <link>{url}</link>\n"
        f"      <guid isPermaLink=\"false\">{guid}</guid>\n"
        f"      <pubDate>{pub_date}</pubDate>\n"
        f"      <dc:creator>Common Ground</dc:creator>\n\n"
        f"      <description><![CDATA[\n{description_text}\n      ]]></description>\n\n"
        f"      <content:encoded><![CDATA[\n{content_html_xml}\n      ]]></content:encoded>\n"
        f"    </item>"
    )

    xml = xml.replace("<item>", new_item + "\n\n    <item>", 1)
    xml = re.sub(
        r"<lastBuildDate>.*?</lastBuildDate>",
        f"<lastBuildDate>{pub_date}</lastBuildDate>",
        xml,
    )

    with open(FEED_XML, "w", encoding="utf-8", newline="\n") as f:
        f.write(xml)

    print(f"  {FEED_XML} updated — prepended {guid}")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    # 1. Determine next post number
    with open(FEED_JSON, "r", encoding="utf-8") as f:
        feed_data = json.load(f)

    latest_num = get_latest_post_number(feed_data)
    next_num   = latest_num + 1
    print(f"Latest post in feed: {latest_num:04d}  →  checking for: {next_num:04d}")

    # 2. Fetch the page and extract all visible text
    print(f"Fetching {SITE_URL} ...")
    resp = requests.get(
        SITE_URL, timeout=30, headers={"User-Agent": "CommonGround-FeedBot/1.0"}
    )
    resp.raise_for_status()

    soup      = BeautifulSoup(resp.text, "html.parser")
    page_text = soup.get_text(separator="\n")

    # Diagnostic: confirm whether post text is present in the raw fetch
    if f"Post {next_num}" in page_text:
        print(f"  DEBUG: 'Post {next_num}' found in raw page text — proceeding")
    else:
        print(f"  DEBUG: 'Post {next_num}' NOT in raw page text — content is likely JS-rendered")
        print(f"  DEBUG: Sample of fetched text (first 300 chars):\n{page_text[:300]}")

    # 3. Find the new post
    lines, post_date = find_post_content(page_text, next_num)
    if lines is None:
        print(f"Post {next_num:04d} not yet published. Nothing to update.")
        sys.exit(0)

    print(f"  Title: {format_title(next_num, post_date)}")

    # 4. Update both feeds
    update_feed_json(next_num, post_date, lines_to_json_html(lines))
    update_feed_xml(
        next_num, post_date,
        lines_to_xml_html(lines),
        lines_to_description(lines),
    )

    print("Done.")


if __name__ == "__main__":
    main()


