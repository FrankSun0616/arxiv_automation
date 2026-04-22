#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import textwrap
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
API_URL = "https://export.arxiv.org/api/query"


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"seen": []}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data.get("seen"), list):
        data["seen"] = []
    return data


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["seen"] = list(dict.fromkeys(state.get("seen", [])))[-2000:]
    with path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")


def collapse(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_time(value: str) -> dt.datetime:
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    return dt.datetime.fromisoformat(value)


def canonical_arxiv_id(arxiv_url: str) -> str:
    raw_id = arxiv_url.rstrip("/").split("/")[-1]
    return re.sub(r"v\d+$", "", raw_id)


def configured_timezone(name: str) -> dt.tzinfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return dt.timezone.utc


def build_query(categories: list[str]) -> str:
    if not categories:
        return "all:*"
    return "(" + " OR ".join(f"cat:{category}" for category in categories) + ")"


def fetch_feed(query: str, max_results: int) -> ET.Element:
    params = {
        "search_query": query,
        "start": "0",
        "max_results": str(max_results),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "frank-arxiv-paper-automation/1.0 "
            "(daily personal research digest)"
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return ET.fromstring(response.read())


def entry_text(entry: ET.Element, name: str) -> str:
    found = entry.find(f"{ATOM}{name}")
    return collapse(found.text if found is not None else "")


def parse_entry(entry: ET.Element) -> dict:
    arxiv_url = entry_text(entry, "id")
    links = entry.findall(f"{ATOM}link")
    pdf_url = ""
    for link in links:
        if link.attrib.get("type") == "application/pdf" or link.attrib.get("title") == "pdf":
            pdf_url = link.attrib.get("href", "")
            break

    authors = [
        collapse(author.findtext(f"{ATOM}name"))
        for author in entry.findall(f"{ATOM}author")
    ]
    categories = [
        category.attrib.get("term", "")
        for category in entry.findall(f"{ATOM}category")
        if category.attrib.get("term")
    ]
    primary = entry.find(f"{ARXIV}primary_category")

    return {
        "id": canonical_arxiv_id(arxiv_url),
        "title": entry_text(entry, "title"),
        "summary": entry_text(entry, "summary"),
        "published": parse_time(entry_text(entry, "published")),
        "updated": parse_time(entry_text(entry, "updated")),
        "authors": [author for author in authors if author],
        "categories": categories,
        "primary_category": primary.attrib.get("term", categories[0] if categories else "")
        if primary is not None
        else (categories[0] if categories else ""),
        "arxiv_url": arxiv_url,
        "pdf_url": pdf_url,
    }


def search_blob(paper: dict) -> str:
    parts = [
        paper["title"],
        paper["summary"],
        " ".join(paper["authors"]),
        " ".join(paper["categories"]),
        paper["primary_category"],
    ]
    return collapse(" ".join(parts)).lower()


def keyword_in_text(blob: str, keyword: str) -> bool:
    normalized = collapse(keyword).lower()
    if not normalized:
        return False
    if re.fullmatch(r"[a-z0-9]+", normalized):
        pattern = rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])"
        return re.search(pattern, blob) is not None
    return normalized in blob


def keyword_matches(paper: dict, keywords: list[str]) -> list[str]:
    blob = search_blob(paper)
    return [keyword for keyword in keywords if keyword_in_text(blob, keyword)]


def author_keyword_matches(paper: dict, keywords: list[str]) -> list[str]:
    blob = collapse(" ".join(paper["authors"])).lower()
    return [keyword for keyword in keywords if keyword_in_text(blob, keyword)]


def collaboration_label(paper: dict, collaboration_priority: list[str]) -> str:
    matches = author_keyword_matches(paper, collaboration_priority)
    if not matches:
        return "CMS/ATLAS"
    match = matches[0].lower()
    if "atlas" in match:
        return "ATLAS"
    if "cms" in match:
        return "CMS"
    return matches[0]


def collaboration_score(paper: dict, collaboration_priority: list[str]) -> int:
    if not collaboration_priority:
        return 0
    matches = author_keyword_matches(paper, collaboration_priority)
    if not matches:
        return 0
    first_match = matches[0]
    for index, keyword in enumerate(collaboration_priority):
        if keyword == first_match:
            return len(collaboration_priority) - index
    return 0


def grouped_keyword_matches(paper: dict, groups: list[dict]) -> dict[str, list[str]]:
    matches = {}
    for group in groups:
        name = group.get("name", "keywords")
        matches[name] = keyword_matches(paper, group.get("keywords", []))
    return matches


def flattened_group_matches(group_matches: dict[str, list[str]]) -> list[str]:
    seen = {}
    for matches in group_matches.values():
        for match in matches:
            seen.setdefault(match, None)
    return list(seen)


def should_include(
    paper: dict,
    *,
    since: dt.datetime,
    seen: set[str],
    require_keywords: list[str],
    require_keyword_groups: list[dict],
    require_author_keywords: list[str],
    exclude_keywords: list[str],
    ignore_state: bool,
    ignore_date: bool,
) -> bool:
    if not ignore_date and paper["published"] < since:
        return False
    if not ignore_state and paper["id"] in seen:
        return False
    if require_keywords and not keyword_matches(paper, require_keywords):
        return False
    if require_keyword_groups:
        group_matches = grouped_keyword_matches(paper, require_keyword_groups)
        if any(not matches for matches in group_matches.values()):
            return False
    if require_author_keywords and not author_keyword_matches(paper, require_author_keywords):
        return False
    if exclude_keywords and keyword_matches(paper, exclude_keywords):
        return False
    return True


def sort_papers(
    papers: list[dict],
    highlight_keywords: list[str],
    priority_keyword_groups: list[dict],
    collaboration_priority: list[str],
) -> list[dict]:
    def score(paper: dict) -> tuple[int, int, int, int, dt.datetime]:
        priority_matches = grouped_keyword_matches(paper, priority_keyword_groups)
        priority_group_hits = sum(1 for matches in priority_matches.values() if matches)
        priority_hit_count = len(flattened_group_matches(priority_matches))
        highlight_count = len(keyword_matches(paper, highlight_keywords))
        return (
            collaboration_score(paper, collaboration_priority),
            priority_group_hits,
            priority_hit_count,
            highlight_count,
            paper["published"],
        )

    return sorted(papers, key=score, reverse=True)


def format_authors(authors: list[str]) -> str:
    if len(authors) <= 6:
        return ", ".join(authors)
    return ", ".join(authors[:6]) + ", et al."


def render_digest(
    *,
    title: str,
    papers: list[dict],
    config: dict,
    query: str,
    generated_at: dt.datetime,
    since: dt.datetime,
    highlight_keywords: list[str],
) -> str:
    lines = [
        f"# {title}",
        "",
        f"Generated: {generated_at.strftime('%Y-%m-%d %H:%M %Z')}",
        f"Window start: {since.astimezone(generated_at.tzinfo).strftime('%Y-%m-%d %H:%M %Z')}",
        f"Query: `{query}`",
        f"New papers: {len(papers)}",
        "",
    ]
    if config.get("require_keyword_groups"):
        required = ", ".join(
            group.get("name", "required")
            for group in config.get("require_keyword_groups", [])
        )
        lines.extend([f"Required groups: {required}", ""])
    if config.get("priority_keyword_groups"):
        priority = ", ".join(
            group.get("name", "priority")
            for group in config.get("priority_keyword_groups", [])
        )
        lines.extend([f"Priority groups: {priority}", ""])
    if config.get("collaboration_priority"):
        collaboration_priority = ", ".join(config.get("collaboration_priority", []))
        lines.extend([f"Collaboration priority: {collaboration_priority}", ""])
    if config.get("require_author_keywords"):
        author_required = ", ".join(config.get("require_author_keywords", []))
        lines.extend([f"Required authors: {author_required}", ""])

    if not papers:
        lines.extend(
            [
                "No new papers matched the current configuration.",
                "",
                "Try increasing `lookback_days`, broadening `categories`, or clearing state with:",
                "",
                "```bash",
                "./run_arxiv_digest.sh --ignore-state",
                "```",
                "",
            ]
        )
        return "\n".join(lines)

    for index, paper in enumerate(papers, start=1):
        published = paper["published"].astimezone(generated_at.tzinfo)
        matches = keyword_matches(paper, highlight_keywords)
        required_matches = grouped_keyword_matches(
            paper, config.get("require_keyword_groups", [])
        )
        priority_matches = grouped_keyword_matches(
            paper, config.get("priority_keyword_groups", [])
        )
        priority_hits = flattened_group_matches(priority_matches)
        author_matches = author_keyword_matches(
            paper, config.get("require_author_keywords", [])
        )
        collaboration = collaboration_label(
            paper, config.get("collaboration_priority", [])
        )
        abstract = textwrap.fill(paper["summary"], width=96)
        lines.extend(
            [
                f"## {index}. {paper['title']}",
                "",
                f"- Collaboration: {collaboration}",
                f"- Authors: {format_authors(paper['authors'])}",
                f"- Published: {published.strftime('%Y-%m-%d %H:%M %Z')}",
                f"- Primary category: `{paper['primary_category']}`",
                f"- Categories: {', '.join(f'`{category}`' for category in paper['categories'])}",
                f"- Links: [arXiv]({paper['arxiv_url']})"
                + (f" | [PDF]({paper['pdf_url']})" if paper["pdf_url"] else ""),
            ]
        )
        if matches:
            lines.append(f"- Keyword hits: {', '.join(matches)}")
        lines.append(
            "- Priority: AI/ML"
            if priority_hits
            else "- Priority: General CMS/ATLAS"
        )
        if priority_hits:
            formatted_priority = "; ".join(
                f"{name}: {', '.join(matches)}"
                for name, matches in priority_matches.items()
                if matches
            )
            lines.append(f"- Priority hits: {formatted_priority}")
        if required_matches:
            formatted_required = "; ".join(
                f"{name}: {', '.join(matches)}"
                for name, matches in required_matches.items()
                if matches
            )
            lines.append(f"- Required hits: {formatted_required}")
        if author_matches:
            lines.append(f"- Required author hits: {', '.join(author_matches)}")
        lines.extend(["", abstract, ""])

    lines.extend(
        [
            "---",
            "",
            "Edit `config.json` to change categories, keywords, and digest size.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(base_dir: Path, output_dir: str, digest: str, now: dt.datetime) -> Path:
    directory = base_dir / output_dir
    directory.mkdir(parents=True, exist_ok=True)
    dated_path = directory / f"arxiv-digest-{now.strftime('%Y-%m-%d')}.md"
    latest_path = directory / "latest.md"
    dated_path.write_text(digest, encoding="utf-8")
    latest_path.write_text(digest, encoding="utf-8")
    return latest_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a daily arXiv Markdown digest.")
    parser.add_argument("--config", default="config.json", help="Path to config JSON.")
    parser.add_argument("--ignore-state", action="store_true", help="Include already-seen papers.")
    parser.add_argument("--ignore-date", action="store_true", help="Do not filter by lookback_days.")
    parser.add_argument("--stdout", action="store_true", help="Print the digest after writing it.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).expanduser().resolve()
    base_dir = config_path.parent
    config = load_config(config_path)
    timezone = configured_timezone(config.get("timezone", "UTC"))
    now = dt.datetime.now(timezone)
    since = now.astimezone(dt.timezone.utc) - dt.timedelta(days=int(config.get("lookback_days", 1)))

    query = build_query(config.get("categories", []))
    feed = fetch_feed(query, int(config.get("api_fetch_limit", 100)))
    entries = feed.findall(f"{ATOM}entry")
    papers = [parse_entry(entry) for entry in entries]

    state_path = base_dir / config.get("state_file", "state/seen.json")
    state = load_state(state_path)
    seen = set(state.get("seen", []))
    selected = [
        paper
        for paper in papers
        if should_include(
            paper,
            since=since,
            seen=seen,
            require_keywords=config.get("require_keywords", []),
            require_keyword_groups=config.get("require_keyword_groups", []),
            require_author_keywords=config.get("require_author_keywords", []),
            exclude_keywords=config.get("exclude_keywords", []),
            ignore_state=args.ignore_state,
            ignore_date=args.ignore_date,
        )
    ]
    selected = sort_papers(
        selected,
        config.get("highlight_keywords", []),
        config.get("priority_keyword_groups", []),
        config.get("collaboration_priority", []),
    )[: int(config.get("max_results", 25))]

    digest = render_digest(
        title=config.get("digest_title", "Daily arXiv Digest"),
        papers=selected,
        config=config,
        query=query,
        generated_at=now,
        since=since,
        highlight_keywords=config.get("highlight_keywords", []),
    )
    latest_path = write_outputs(base_dir, config.get("output_dir", "digests"), digest, now)

    if not args.ignore_state:
        state.setdefault("seen", [])
        state["seen"].extend(paper["id"] for paper in selected)
        state["updated_at"] = now.isoformat()
        state["last_digest"] = str(latest_path)
        save_state(state_path, state)

    result = {
        "digest": str(latest_path),
        "new_papers": len(selected),
        "fetched_entries": len(entries),
    }
    print(json.dumps(result, indent=2))
    if args.stdout:
        print()
        print(digest)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"arxiv_digest.py: {exc}", file=sys.stderr)
        raise SystemExit(1)
