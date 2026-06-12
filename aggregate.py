"""Aggregate multiple podcast RSS feeds into a single Spotify-ready feed.xml."""
import sys
from datetime import datetime, timezone
from pathlib import Path

import truststore
truststore.inject_into_ssl()

import feedparser
import requests
import yaml
from feedgen.feed import FeedGenerator

ROOT = Path(__file__).parent
CONFIG = ROOT / "feeds.yaml"
OUTPUT = ROOT / "feed.xml"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0"
ACCEPT = "application/rss+xml, application/xml;q=0.9, */*;q=0.8"

# Correções de texto aplicadas às descrições vindas das fontes (typos no Substack).
# Chave = texto original (com typo), valor = texto corrigido.
TEXT_CORRECTIONS = {
    "Noto first block": "Novo first block",
}


def apply_corrections(text):
    if not text:
        return text
    for wrong, right in TEXT_CORRECTIONS.items():
        text = text.replace(wrong, right)
    return text


def load_config():
    with open(CONFIG, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_pubdate(entry):
    if getattr(entry, "published_parsed", None):
        return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    if getattr(entry, "updated_parsed", None):
        return datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def get_enclosure(entry):
    for enc in getattr(entry, "enclosures", []) or []:
        url = enc.get("href") or enc.get("url")
        if url:
            return {
                "url": url,
                "length": str(enc.get("length") or "0"),
                "type": enc.get("type") or "audio/mpeg",
            }
    return None


def entry_guid(entry):
    return (
        getattr(entry, "id", None)
        or getattr(entry, "guid", None)
        or getattr(entry, "link", None)
    )


def fetch_feed(url):
    r = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": ACCEPT},
        timeout=30,
    )
    r.raise_for_status()
    return r.content


def collect_entries(urls):
    seen = set()
    items = []
    for url in urls:
        print(f"Fetching: {url}")
        try:
            content = fetch_feed(url)
        except Exception as e:
            print(f"  ERR: {e}")
            continue
        print(f"  got {len(content)} bytes")
        parsed = feedparser.parse(content)
        if parsed.bozo:
            print(f"  WARN: {parsed.bozo_exception}")
        for e in parsed.entries:
            guid = entry_guid(e)
            if not guid or guid in seen:
                continue
            enc = get_enclosure(e)
            if not enc:
                continue
            seen.add(guid)
            items.append({
                "guid": guid,
                "title": getattr(e, "title", "(no title)"),
                "summary": apply_corrections(getattr(e, "summary", "") or getattr(e, "description", "")),
                "link": getattr(e, "link", enc["url"]),
                "pubdate": parse_pubdate(e),
                "enclosure": enc,
                "duration": getattr(e, "itunes_duration", None),
            })
        print(f"  -> {len(parsed.entries)} entries seen, {len(items)} total kept")
    items.sort(key=lambda x: x["pubdate"], reverse=True)
    return items


def build_feed(show, items):
    fg = FeedGenerator()
    fg.load_extension("podcast")

    fg.title(show["title"])
    fg.link(href=show["link"], rel="alternate")
    fg.description(show["description"])
    fg.language(show.get("language", "pt-BR"))
    fg.author({"name": show["author"], "email": show.get("email", "")})
    fg.image(show["image"])

    fg.podcast.itunes_author(show["author"])
    fg.podcast.itunes_summary(show["description"])
    fg.podcast.itunes_owner(name=show["author"], email=show.get("email", ""))
    fg.podcast.itunes_image(show["image"])
    fg.podcast.itunes_category(show.get("category", "Technology"))
    fg.podcast.itunes_explicit("yes" if show.get("explicit") else "no")

    for it in items:
        fe = fg.add_entry()
        fe.id(it["guid"])
        fe.title(it["title"])
        fe.description(it["summary"])
        fe.link(href=it["link"])
        fe.pubDate(it["pubdate"])
        fe.enclosure(
            it["enclosure"]["url"],
            it["enclosure"]["length"],
            it["enclosure"]["type"],
        )
        if it.get("duration"):
            try:
                fe.podcast.itunes_duration(str(it["duration"]))
            except Exception:
                pass

    return fg


def main():
    cfg = load_config()
    show = cfg["show"]
    feeds = cfg.get("feeds") or []
    if not feeds:
        print("No feeds configured in feeds.yaml")
        sys.exit(1)
    items = collect_entries(feeds)
    print(f"Collected {len(items)} unique episodes across {len(feeds)} feeds")
    fg = build_feed(show, items)
    fg.rss_file(str(OUTPUT), pretty=True)
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
