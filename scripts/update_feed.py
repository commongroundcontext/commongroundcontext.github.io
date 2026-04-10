#!/usr/bin/env python3
"""
Scrapes the latest post from commongroundcontext.com and prepends it
to feed.json and feed.xml.

Run automatically every Sunday via GitHub Actions, or manually via
workflow_dispatch. Exits cleanly (code 0) if the next post is not yet
published, so the workflow never fails on a quiet Sunday.
"""

import json
import re
import sys
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

SITE_URL = "https://commongroundcontext.com/"
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


def find_post_element(soup: BeautifulSoup, post_num: int):
    """
    Try several strategies to locate the HTML element that wraps the post.
    Returns a Tag or None.
    """
    post_id = f"post{post_num:04d}"

    # Strategy 1: any element whose id attribute equals "post0011"
    el = soup.find(id=post_id)
    if el is not None:
        print(f"  Found via id='{post_id}' (<{el.name}>)")
        return el

    # Strategy 2: <a name="post0011"> — walk up to nearest block container
    anchor = soup.find("a", attrs={"name": post_id})
    if anchor:
        for parent in anchor.parents:
            if parent.name in ("section", "article", "div"):
                print(f"  Found via <a name='{post_id}'>, parent <{parent.name}>")
                return parent
        return anchor.parent

    # Strategy 3: heading whose text contains "Post NNN" (e.g. "Post 11")
    for tag in ("h1", "h2", "h3", "h4"):
        heading = soup.find(
            tag, string=re.compile(rf"Post\s+0*{post_num}\b", re.IGNORECASE)
        )
        if heading:
            container = heading.parent
            print(f"  Found via heading text in <{tag}>, parent <{container.name}>")
            return container

    print(f"  No element found for post {post_num:04d}")
    return None


def extract_paragraphs(element) -> list:
    """Return all non-empty <p> descendants of an element."""
    return [p for p in element.find_all("p") if p.get_text().strip()]


def format_title(post_num: int, post_date: datetime) -> str:
    """'Post 0011 — April 12, 2026'"""
    return f"Post {post_num:04d} \u2014 {post_date.strftime('%B')} {post_date.day}, {post_date.year}"


def to_json_html(paragraphs: list) -> str:
    """Single-line concatenation of <p>text</p> tags (JSON Feed style)."""
    return "".join(f"<p>{p.get_text()}</p>" for p in paragraphs)


def to_xml_html(paragraphs: list) -> str:
    """One <p>text</p> per line (RSS content:encoded style)."""
    return "\n".join(f"<p>{p.get_text()}</p>" for p in paragraphs)


def to_description(paragraphs: list, lines: int = 3) -> str:
    """Plain-text snippet of the first N paragraphs (RSS description)."""
    return "\n".join(p.get_text().strip() for p in paragraphs[:lines])


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

    # Prepend before the first existing <item>
    xml = xml.replace("<item>", new_item + "\n\n    <item>", 1)

    # Refresh lastBuildDate
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
    # 1. Determine which post number to look for
    with open(FEED_JSON, "r", encoding="utf-8") as f:
        feed_data = json.load(f)

    latest_num = get_latest_post_number(feed_data)
    next_num   = latest_num + 1
    print(f"Latest post in feed: {latest_num:04d}  →  checking for: {next_num:04d}")

    # 2. Fetch the live website
    print(f"Fetching {SITE_URL} ...")
    resp = requests.get(SITE_URL, timeout=30, headers={"User-Agent": "CommonGround-FeedBot/1.0"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # 3. Locate the new post element
    el = find_post_element(soup, next_num)
    if el is None:
        print(f"Post {next_num:04d} not yet published. Nothing to update.")
        sys.exit(0)

    paragraphs = extract_paragraphs(el)
    if not paragraphs:
        print("ERROR: Post element found but contains no <p> tags.")
        print("       The site HTML structure may have changed — inspect manually.")
        sys.exit(1)

    print(f"  Extracted {len(paragraphs)} paragraph(s)")

    # 4. Build content in the two required formats
    content_json = to_json_html(paragraphs)
    content_xml  = to_xml_html(paragraphs)
    description  = to_description(paragraphs)

    # Post date = today (the workflow runs on Sunday)
    post_date = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    print(f"  Title: {format_title(next_num, post_date)}")

    # 5. Write both feeds
    update_feed_json(next_num, post_date, content_json)
    update_feed_xml(next_num, post_date, content_xml, description)

    print("Done.")


if __name__ == "__main__":
    main()

