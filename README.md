# arXiv Paper Automation

This folder contains a small, dependency-free daily arXiv digest workflow.

## Run It

```bash
cd /Volumes/Frank_T9/arxiv_automation
./run_arxiv_digest.sh
```

The digest is written to:

- `digests/latest.md`
- `digests/arxiv-digest-YYYY-MM-DD.md`

The script also keeps `state/seen.json` so daily runs only show papers that have
not already appeared in a previous digest.

## Customize Topics

Edit `config.json`.

- `categories`: arXiv categories to watch. The current default watches
  `hep-ex`, `physics.ins-det`, and `physics.data-an`.
- `priority_keyword_groups`: terms that push papers higher in the digest. The
  current default prioritizes AI/ML methods.
- `collaboration_priority`: collaboration ordering. The current default puts
  ATLAS Collaboration papers before CMS Collaboration papers.
- `include_priority_matches_without_required_authors`: when true, AI/ML
  experimental HEP papers from the watched categories are included even if they
  are not CMS or ATLAS papers.
- `highlight_keywords`: terms that lift papers higher in the digest.
- `api_timeout_seconds`: network timeout for the arXiv API request.
- `api_retry_attempts`: how many times the arXiv fetch should retry after
  transient failures such as rate limits or timeouts.
- `api_retry_delay_seconds`: base retry delay for the arXiv fetch. Later
  retries back off exponentially, and `Retry-After` is respected when arXiv
  provides it.
- `require_keywords`: leave empty to include all papers from the categories, or
  add terms to require at least one match.
- `require_keyword_groups`: grouped filters. Leave empty for the current broad
  mode, where AI/ML is a priority but not a requirement.
- `require_author_keywords`: author-list filters. The current default keeps
  official CMS Collaboration or ATLAS Collaboration papers, while AI/ML
  priority matches can also be included through the setting above.
- `exclude_keywords`: terms to hide.
- `lookback_days`: how far back the first run should look.
- `max_results`: maximum papers in one digest.

## Useful Commands

Preview without the seen-paper filter:

```bash
./run_arxiv_digest.sh --ignore-state
```

Print the generated digest in the terminal:

```bash
./run_arxiv_digest.sh --stdout
```

## Daily Automation Command

Use this command from a scheduler or Codex automation:

```bash
/Volumes/Frank_T9/arxiv_automation/run_arxiv_digest.sh
```

## GitHub Actions + Gmail

This folder is ready to run from GitHub Actions and email the digest through
Gmail every day. The workflow file is:

```text
.github/workflows/daily-arxiv-gmail.yml
```

It runs at 08:17 Hong Kong time every day and can also be started manually from
the GitHub Actions tab.

### 1. Create a GitHub repository

From this folder:

```bash
git init
git add .gitignore README.md arxiv_digest.py config.json run_arxiv_digest.sh send_digest_email.py .github/workflows/daily-arxiv-gmail.yml state/.gitkeep state/seen.json
git commit -m "Add daily arXiv Gmail digest workflow"
git branch -M main
git remote add origin git@github.com:YOUR_USER/YOUR_REPO.git
git push -u origin main
```

### 2. Create a Gmail app password

Use a Gmail App Password, not your normal Gmail password. Google requires
2-Step Verification before App Passwords are available.

### 3. Add GitHub repository secrets

In the GitHub repo, open:

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

Add these secrets:

```text
GMAIL_USER
GMAIL_APP_PASSWORD
ARXIV_DIGEST_RECIPIENTS
```

Example values:

```text
GMAIL_USER=haoxuansun0616@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
ARXIV_DIGEST_RECIPIENTS=haoxuansun0616@gmail.com
```

Multiple recipients can be comma-separated.

### 4. Allow state commits

The workflow commits `state/seen.json` after each successful run so the same
papers are not emailed repeatedly. If GitHub blocks that push, check:

```text
Settings -> Actions -> General -> Workflow permissions -> Read and write permissions
```

Branch protection can also block the bot commit; if that happens, use a private
repo without branch protection for this automation.

### Email format

The email is sent as a multipart message:

- a styled HTML digest with summary chips and paper cards
- cleaned-up math/LaTeX text for email readability
- a plain-text Markdown fallback
- the Markdown digest attached as `latest.md`

### 5. Test it

On GitHub, go to:

```text
Actions -> Daily Experimental HEP AI/ML arXiv Gmail Digest -> Run workflow
```

Use `dry_run=true` first to confirm the workflow runs in GitHub Actions without
sending email or changing `state/seen.json`. After the Gmail secrets are set,
run it again with `dry_run=false` to send one real test email. For a rich manual
test that includes already-seen papers without changing state, use
`dry_run=false` and `preview_all=true`.

If both runs succeed, the daily scheduled email is set.
