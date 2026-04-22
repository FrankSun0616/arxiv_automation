#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import html
import os
import re
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path


def env(name: str, fallback: str | None = None) -> str | None:
    return os.environ.get(name) or fallback


def required_env(name: str) -> str:
    value = env(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def parse_new_papers(markdown: str) -> int | None:
    match = re.search(r"^New papers:\s*(\d+)\s*$", markdown, flags=re.MULTILINE)
    return int(match.group(1)) if match else None


def parse_title(markdown: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "arXiv Digest"


def subject_for(markdown: str) -> str:
    title = parse_title(markdown)
    count = parse_new_papers(markdown)
    today = dt.datetime.now().strftime("%Y-%m-%d")
    if count is None:
        return f"{title} - {today}"
    noun = "paper" if count == 1 else "papers"
    return f"{title} - {count} new {noun} - {today}"


def clean_inline_markdown(value: str) -> str:
    value = value.replace("`", "")
    return re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", value).strip()


def latex_to_text(value: str) -> str:
    replacements = {
        "\\sqrt": "sqrt",
        "\\mathrm": "",
        "\\textrm": "",
        "\\text": "",
        "\\mathbf": "",
        "\\mathit": "",
        "\\mathcal": "",
        "\\bar": "bar",
        "\\overline": "bar",
        "\\ell": "l",
        "\\gamma": "gamma",
        "\\Gamma": "Gamma",
        "\\phi": "phi",
        "\\Phi": "Phi",
        "\\psi": "psi",
        "\\Psi": "Psi",
        "\\mu": "mu",
        "\\nu": "nu",
        "\\tau": "tau",
        "\\kappa": "kappa",
        "\\lambda": "lambda",
        "\\Delta": "Delta",
        "\\Upsilon": "Upsilon",
        "\\pm": "+/-",
        "\\times": "x",
        "\\to": "->",
        "\\rightarrow": "->",
        "\\gt": ">",
        "\\lt": "<",
        "\\%": "%",
        "\\,": " ",
        "\\;": " ",
        "\\!": "",
    }
    text = value
    text = text.replace("\\\\", "\\")
    text = text.replace("``", '"').replace("''", '"')
    text = re.sub(r"\$\$+", " ", text)
    text = text.replace("$", "")
    text = text.replace("~", " ")
    for source, target in replacements.items():
        if not source[1:].isalpha():
            text = text.replace(source, target)
    text = re.sub(r"\\(?:bar|overline)\{([^{}]+)\}", r"\1-bar", text)
    text = re.sub(r"\\(?:mathrm|textrm|text|mathbf|mathit|mathcal)\{([^{}]+)\}", r"\1", text)
    text = re.sub(r"\\sqrt\{([^{}]+)\}", r"sqrt(\1)", text)
    text = text.replace("{", "").replace("}", "")
    text = re.sub(r"\\([A-Za-z]+)", lambda match: replacements.get("\\" + match.group(1), match.group(1)), text)
    text = text.replace("^", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def html_text(value: str) -> str:
    return html.escape(latex_to_text(value))


def parse_metadata(markdown: str) -> dict[str, str]:
    metadata = {"Title": parse_title(markdown)}
    for line in markdown.splitlines():
        if line.startswith("## "):
            break
        match = re.match(r"^([A-Za-z ]+):\s*(.*)$", line)
        if match:
            metadata[match.group(1)] = clean_inline_markdown(match.group(2))
    return metadata


def parse_markdown_links(value: str) -> dict[str, str]:
    return {
        label: url
        for label, url in re.findall(r"\[([^\]]+)\]\(([^)]+)\)", value)
    }


def parse_papers(markdown: str) -> list[dict]:
    pieces = re.split(r"^##\s+\d+\.\s+", markdown, flags=re.MULTILINE)
    headings = re.findall(r"^##\s+\d+\.\s+(.*)$", markdown, flags=re.MULTILINE)
    papers = []
    for title, block in zip(headings, pieces[1:]):
        fields = {}
        abstract_lines = []
        in_fields = False
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if line == "---":
                break
            if not line:
                continue
            if line.startswith("- "):
                in_fields = True
                if ":" in line:
                    key, value = line[2:].split(":", 1)
                    fields[key.strip()] = value.strip()
                continue
            if in_fields:
                abstract_lines.append(line)

        links = parse_markdown_links(fields.get("Links", ""))
        keyword_hits = [
            item.strip()
            for item in clean_inline_markdown(fields.get("Keyword hits", "")).split(",")
            if item.strip()
        ]
        papers.append(
            {
                "title": title.strip(),
                "collaboration": clean_inline_markdown(fields.get("Collaboration", "")),
                "inclusion": clean_inline_markdown(fields.get("Inclusion", "")),
                "authors": clean_inline_markdown(fields.get("Authors", "")),
                "published": clean_inline_markdown(fields.get("Published", "")),
                "primary_category": clean_inline_markdown(fields.get("Primary category", "")),
                "categories": clean_inline_markdown(fields.get("Categories", "")),
                "priority": clean_inline_markdown(fields.get("Priority", "General HEP")),
                "priority_hits": clean_inline_markdown(fields.get("Priority hits", "")),
                "keyword_hits": keyword_hits,
                "arxiv_url": links.get("arXiv", ""),
                "pdf_url": links.get("PDF", ""),
                "abstract": " ".join(abstract_lines),
            }
        )
    return papers


def badge(text: str, *, color: str = "#1f6feb", background: str = "#eef5ff") -> str:
    return (
        f'<span style="display:inline-block;margin:0 6px 6px 0;padding:4px 8px;'
        f'border-radius:999px;background:{background};color:{color};font-size:12px;'
        f'font-weight:600;">{html.escape(text)}</span>'
    )


def link_button(label: str, url: str, *, primary: bool = False) -> str:
    if not url:
        return ""
    background = "#1f6feb" if primary else "#ffffff"
    color = "#ffffff" if primary else "#1f2937"
    border = "#1f6feb" if primary else "#d1d5db"
    return (
        f'<a href="{html.escape(url, quote=True)}" style="display:inline-block;'
        f'padding:8px 12px;border-radius:6px;border:1px solid {border};'
        f'background:{background};color:{color};text-decoration:none;'
        f'font-size:13px;font-weight:700;margin-right:8px;">{html.escape(label)}</a>'
    )


def render_paper_card(paper: dict, index: int) -> str:
    is_priority = paper["priority"].lower().startswith("ai/ml")
    collaboration = paper.get("collaboration", "")
    collaboration_upper = collaboration.upper()
    is_atlas = collaboration_upper.startswith("ATLAS")
    is_cms = collaboration_upper.startswith("CMS")
    collaboration_badge = badge(
        collaboration if (is_atlas or is_cms) else "AI/ML HEP",
        color="#1d4ed8" if is_atlas else ("#0f766e" if is_cms else "#7c2d12"),
        background="#dbeafe" if is_atlas else ("#ccfbf1" if is_cms else "#fff4e6"),
    )
    inclusion_badge = badge(
        paper.get("inclusion") or "Experimental HEP",
        color="#4b5563",
        background="#f8fafc",
    )
    priority_badge = badge(
        "AI/ML priority" if is_priority else "General HEP",
        color="#7c2d12" if is_priority else "#374151",
        background="#fff4e6" if is_priority else "#f3f4f6",
    )
    keyword_badges = "".join(badge(item, color="#4b5563", background="#f8fafc") for item in paper["keyword_hits"][:8])
    title_link = paper["arxiv_url"] or paper["pdf_url"] or "#"
    abstract = html.escape(paper["abstract"])
    abstract = html_text(paper["abstract"])
    if len(abstract) > 1200:
        abstract = abstract[:1197].rstrip() + "..."
    return f"""
      <article style="border:1px solid #e5e7eb;border-radius:8px;padding:18px;margin:0 0 16px;background:#ffffff;">
        <div style="font-size:13px;color:#6b7280;font-weight:700;margin-bottom:8px;">Paper {index}</div>
        <h2 style="font-size:19px;line-height:1.35;margin:0 0 10px;color:#111827;">
          <a href="{html.escape(title_link, quote=True)}" style="color:#111827;text-decoration:none;">{html_text(paper["title"])}</a>
        </h2>
        <div style="margin-bottom:8px;">{collaboration_badge}{priority_badge}{inclusion_badge}</div>
        <p style="margin:0 0 4px;color:#374151;font-size:14px;"><strong>Authors:</strong> {html_text(paper["authors"])}</p>
        <p style="margin:0 0 4px;color:#374151;font-size:14px;"><strong>Published:</strong> {html_text(paper["published"])}</p>
        <p style="margin:0 0 12px;color:#374151;font-size:14px;"><strong>Primary category:</strong> {html_text(paper["primary_category"])}</p>
        <p style="margin:0 0 14px;color:#1f2937;font-size:15px;line-height:1.55;">{abstract}</p>
        <div style="margin-bottom:12px;">{keyword_badges}</div>
        <div>
          {link_button("arXiv", paper["arxiv_url"], primary=True)}
          {link_button("PDF", paper["pdf_url"])}
        </div>
      </article>
    """


def render_html_email(markdown: str) -> str:
    metadata = parse_metadata(markdown)
    papers = parse_papers(markdown)
    priority_count = sum(1 for paper in papers if paper["priority"].lower().startswith("ai/ml"))
    atlas_count = sum(1 for paper in papers if paper.get("collaboration", "").upper().startswith("ATLAS"))
    cms_count = sum(1 for paper in papers if paper.get("collaboration", "").upper().startswith("CMS"))
    other_hep_count = max(0, len(papers) - atlas_count - cms_count)
    general_count = max(0, len(papers) - priority_count)
    paper_cards = "\n".join(render_paper_card(paper, index) for index, paper in enumerate(papers, 1))
    if not paper_cards:
        paper_cards = (
            '<div style="border:1px solid #e5e7eb;border-radius:8px;padding:18px;background:#ffffff;">'
            "No new papers matched the current configuration.</div>"
        )

    return f"""<!doctype html>
<html>
  <body style="margin:0;background:#f5f7fb;color:#111827;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;">
    <div style="display:none;max-height:0;overflow:hidden;">{len(papers)} experimental HEP arXiv papers, with AI/ML papers first.</div>
    <main style="max-width:760px;margin:0 auto;padding:24px 14px;">
      <section style="background:#111827;color:#ffffff;border-radius:8px;padding:22px;margin-bottom:16px;">
        <p style="margin:0 0 8px;font-size:13px;color:#cbd5e1;font-weight:700;">Experimental HEP arXiv digest</p>
        <h1 style="margin:0 0 12px;font-size:26px;line-height:1.2;">{html.escape(metadata.get("Title", "arXiv Digest"))}</h1>
        <p style="margin:0;color:#d1d5db;font-size:14px;">Generated {html.escape(metadata.get("Generated", ""))}</p>
      </section>
      <section style="display:block;background:#ffffff;border:1px solid #e5e7eb;border-radius:8px;padding:16px;margin-bottom:16px;">
        {badge(f"{len(papers)} new papers", color="#075985", background="#e0f2fe")}
        {badge(f"{atlas_count} ATLAS", color="#1d4ed8", background="#dbeafe")}
        {badge(f"{cms_count} CMS", color="#0f766e", background="#ccfbf1")}
        {badge(f"{other_hep_count} other HEP", color="#7c2d12", background="#fff4e6")}
        {badge(f"{priority_count} AI/ML priority", color="#7c2d12", background="#fff4e6")}
        {badge(f"{general_count} general", color="#374151", background="#f3f4f6")}
        <p style="margin:8px 0 0;color:#4b5563;font-size:14px;">Window start: {html.escape(metadata.get("Window start", ""))}</p>
        <p style="margin:4px 0 0;color:#4b5563;font-size:14px;">Includes official CMS/ATLAS papers plus AI/ML experimental HEP papers from watched arXiv categories.</p>
      </section>
      {paper_cards}
      <p style="color:#6b7280;font-size:12px;line-height:1.5;margin:18px 0 0;">
        AI/ML experimental HEP papers are ranked first, with ATLAS prioritized inside that group and among general collaboration papers. The Markdown digest is attached.
      </p>
    </main>
  </body>
</html>"""


def build_message(
    *,
    sender: str,
    sender_name: str,
    recipients: list[str],
    subject: str,
    body: str,
    digest_path: Path,
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = f"{sender_name} <{sender}>" if sender_name else sender
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)
    message.add_alternative(render_html_email(body), subtype="html")
    message.add_attachment(
        body.encode("utf-8"),
        maintype="text",
        subtype="markdown",
        filename=digest_path.name,
    )
    return message


def send_message(message: EmailMessage, *, username: str, password: str, host: str, port: int) -> None:
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as server:
        server.login(username, password)
        server.send_message(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Email the generated arXiv digest via Gmail SMTP.")
    parser.add_argument("--digest", default="digests/latest.md", help="Markdown digest to email.")
    parser.add_argument("--dry-run", action="store_true", help="Build the email but do not send it.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    digest_path = Path(args.digest).expanduser().resolve()
    if not digest_path.exists():
        raise SystemExit(f"Digest does not exist: {digest_path}")

    body = digest_path.read_text(encoding="utf-8")
    gmail_user = required_env("GMAIL_USER")
    gmail_password = required_env("GMAIL_APP_PASSWORD").replace(" ", "")
    recipients = [
        item.strip()
        for item in required_env("ARXIV_DIGEST_RECIPIENTS").split(",")
        if item.strip()
    ]
    if not recipients:
        raise SystemExit("ARXIV_DIGEST_RECIPIENTS did not contain any recipients")

    subject = env("ARXIV_DIGEST_SUBJECT") or subject_for(body)
    sender_name = env("ARXIV_DIGEST_SENDER_NAME", "arXiv Digest") or ""
    host = env("SMTP_HOST", "smtp.gmail.com") or "smtp.gmail.com"
    port = int(env("SMTP_PORT", "465") or "465")

    message = build_message(
        sender=gmail_user,
        sender_name=sender_name,
        recipients=recipients,
        subject=subject,
        body=body,
        digest_path=digest_path,
    )

    if args.dry_run:
        print(f"Dry run: would send '{subject}' to {', '.join(recipients)}")
        print(f"Dry run: HTML paper cards built: {len(parse_papers(body))}")
        return 0

    send_message(message, username=gmail_user, password=gmail_password, host=host, port=port)
    print(f"Sent '{subject}' to {', '.join(recipients)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"send_digest_email.py: {exc}", file=sys.stderr)
        raise SystemExit(1)
