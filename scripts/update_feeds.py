#!/usr/bin/env python3
"""
update_feeds.py
---------------
Checks commongroundcontext.com for the next weekly post and, if found,
prepends it to feed.json and feed.xml in the repo root.

Run via GitHub Actions every Sunday (see .github/workflows/update-feeds.yml).

HTML assumption
---------------
The source page contains elements like:
    <section id="post0011"> ... <p>line of text</p> ... </section>

If your markup uses <span class="p"> instead of <p>, the fallback branch
handles that automatically.  Adjust PARA_SELECTOR if your structure differs.
"""

import json
import re
import sys
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

# ── Configuration ─────────────────────────────────────────────────────────────
SOURCE_URL  = "https://commongroundcontext.com/"
FEED_JSON   = "feed.json"
FEED_XML    = "feed.xml"
AUTHOR_NAME = "Common Ground"
# ─────────────────────────────────────────────────────────────────────────────


def latest_post_number(items: list) -> int:
    """Return the highest post number already present in the feed."""
    nums = [
        int(m.group(1))
        for item in items
        if (m := re.search(r"-(\d+)$", item.get("id", "")))
    ]
    return max(nums) if nums else 0


def fetch_post_lines(post_num: int) -> list[str] | None:
    """
    Fetch the source page and return the text lines for the given post number,
    or None if the post element is not yet present.
    """
    post_id = f"post{post_num:04d}"
    resp = requests.get(SOURCE_URL, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    post_el = soup.find(id=post_id)
    if post_el is None:
        return None

    # Primary: real <p> tags
    tags = post_el.find_all("p")
    # Fallback: Webflow-style <span class="p">
    if not tags:
        tags = post_el.find_all("span", class_="p")

    lines = [t.get_text(strip=True) for t in tags if t.get_text(strip=True)]
    return lines if lines else None


# ── Content builders ──────────────────────────────────────────────────────────

def content_html_oneline(lines: list[str]) -> str:
    """Single-line content_html for JSON Feed."""
    return "".join(f"<p>{line}</p>" for line in lines)


def content_html_multiline(lines: list[str]) -> str:
    """Multi-line content_html for RSS <content:encoded>."""
    return "\n".join(f"<p>{line}</p>" for line in lines)


def description_snippet(lines: list[str], max_lines: int = 3) -> str:
    return "\n".join(lines[:max_lines])


# ── Feed writers ──────────────────────────────────────────────────────────────

def prepend_json(post_num: int, title: str, url: str,
                 date_iso: str, content: str) -> None:
    with open(FEED_JSON, encoding="utf-8") as f:
        data = json.load(f)

    data["items"].insert(0, {
        "id":             f"commonground-post-{post_num:04d}",
        "title":          title,
        "url":            url,
        "date_published": date_iso,
        "content_html":   content,
    })

    with open(FEED_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def prepend_xml(post_num: int, title: str, url: str,
                date_rss: str, description: str, content: str) -> None:
    with open(FEED_XML, encoding="utf-8") as f:
        xml = f.read()

    guid = f"commonground-post-{post_num:04d}"

    new_item = (
        f"\n    <item>\n"
        f"      <title>{title}</title>\n"
        f"      <link>{url}</link>\n"
        f"      <guid isPermaLink=\"false\">{guid}</guid>\n"
        f"      <pubDate>{date_rss}</pubDate>\n"
        f"      <dc:creator>{AUTHOR_NAME}</dc:creator>\n\n"
        f"      <description><![CDATA[\n{description}\n      ]]></description>\n\n"
        f"      <content:encoded><![CDATA[\n{content}\n      ]]></content:encoded>\n"
        f"    </item>"
    )

    # Refresh lastBuildDate
    today_rss = datetime.now(timezone.utc).strftime("%a, %d %b %Y 00:00:00 GMT")
    xml = re.sub(
        r"<lastBuildDate>.*?</lastBuildDate>",
        f"<lastBuildDate>{today_rss}</lastBuildDate>",
        xml,
    )

    # Insert new item before the first existing <item>
    xml = xml.replace("\n    <item>", f"{new_item}\n\n    <item>", 1)

    with open(FEED_XML, "w", encoding="utf-8") as f:
        f.write(xml)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    today = datetime.now(timezone.utc)

    with open(FEED_JSON, encoding="utf-8") as f:
        feed_data = json.load(f)

    current  = latest_post_number(feed_data["items"])
    next_num = current + 1

    print(f"Feed is current through post{current:04d}. Checking for post{next_num:04d}…")

    lines = fetch_post_lines(next_num)
    if lines is None:
        print(f"post{next_num:04d} not found on source site yet. Nothing to update.")
        sys.exit(0)

    print(f"Found post{next_num:04d} ({len(lines)} lines). Updating feeds…")

    # Build shared metadata
    day       = today.day                              # no leading zero
    date_label = today.strftime(f"%B {day}, %Y")      # e.g. "April 6, 2026"
    title     = f"Post {next_num:04d} \u2014 {date_label}"
    url       = f"{SOURCE_URL}#post{next_num:04d}"
    date_iso  = today.strftime("%Y-%m-%dT00:00:00Z")
    date_rss  = today.strftime("%a, %d %b %Y 00:00:00 GMT")

    prepend_json(next_num, title, url, date_iso, content_html_oneline(lines))
    prepend_xml(next_num, title, url, date_rss,
                description_snippet(lines), content_html_multiline(lines))

    print("feed.json and feed.xml updated successfully.")


if __name__ == "__main__":
    main()
