#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
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
