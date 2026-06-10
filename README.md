# Managed OpenClaw skills

This directory is the OpenClaw **managed skills root** (`~/.openclaw/skills/`).
Each subdirectory is one skill, loadable by the Gateway.

This directory is **also a single git repository** for local version control
and (optionally) cross-machine sync. Git is the source of truth; ClawHub is
the distribution channel — they do not conflict.

## Layout

```
~/.openclaw/skills/                    # this git repo
├── .git/
├── .gitignore
├── README.md                          # this file
└── <skill-name>/                      # one skill per subdirectory
    ├── SKILL.md                       # required: frontmatter + body
    ├── scripts/                       # production code (optional)
    ├── tests/                         # see skill-testing skill
    │   ├── unit/
    │   └── integration/
    └── ...
```

A skill's directory name is also its **slug** (the part OpenClaw and ClawHub
use to identify it). The convention `test_<module>.<ext>` is required for
test files; see the `skill-testing` skill for the full rules.

## Why one repo, not one repo per skill

- One `git init` covers every skill in this directory.
- Commits group related changes across skills (e.g. an OpenClaw upgrade that
  touches three skills).
- Publishing a single skill to ClawHub still works — you point the publish
  command at the subdirectory, not the whole repo.

## Daily workflow

```bash
cd ~/.openclaw/skills

# after editing <skill>/
git status                                # see what changed
git add <skill-name>/                     # stage one skill
git diff --cached                         # review before committing
git commit -m "<skill-name>: <what changed>"
```

Commit messages should be `<skill-slug>: <imperative summary>` so `git log`
on a single skill stays readable.

## Optional: sync to a git remote (backup / cross-machine)

```bash
cd ~/.openclaw/skills
git remote add origin <your-git-url>      # one-time
git push -u origin master                 # first push
# later
git push
```

Use a private Gitea / GitLab / GitHub repo. The remote is **separate** from
ClawHub — pushing to git does not publish to ClawHub.

## Optional: publish to ClawHub

ClawHub is the public OpenClaw skill registry at <https://clawhub.ai>. It
requires:

1. The standalone `clawhub` CLI (separate install — not preinstalled).
2. A ClawHub owner handle (e.g. `@your-name` or an org you belong to).
3. You to run the publish command yourself; agents do not push to ClawHub.

Publishing workflow (when you're ready):

```bash
cd ~/.openclaw/skills

# 1. freeze a version in git first (recommended)
git tag <skill-name>-v0.1.0
git push origin <skill-name>-v0.1.0      # if you have a remote

# 2. then publish the directory
clawhub login                            # one-time per machine
clawhub skill publish <skill-name>/ --version 0.1.0
```

The ClawHub server validates the owner scope, slug, and version. If anything
mismatches, the publish is rejected — no partial state is created.

To **unpublish or fix a bad release**, use `clawhub` commands; do not edit
files on the server directly. See `clawhub --help` and
<https://docs.openclaw.ai/clawhub/cli>.

## What NOT to put in this repo

- **Secrets** (API keys, tokens, private certs). The `.gitignore` excludes
  common patterns; review every `git add` and `git diff --cached` before
  committing.
- **Large binary artifacts** (models, datasets). Use a separate storage path
  and reference by URL inside the skill.
- **Other OpenClaw config** (`openclaw.json`, agent files, session logs).
  Those live in `~/.openclaw/` and are managed by the Gateway, not by you.
- **Other people's skills from ClawHub.** Those install into
  `~/.openclaw/skills/<name>/` automatically; commits here should be for
  your own work, not vendored copies. If you want to modify an installed
  skill, fork it first.

## Recovery

This is local-only git. To roll back a bad change to a single skill:

```bash
cd ~/.openclaw/skills
git log --oneline -- <skill-name>/       # find the bad commit
git revert <commit-sha>                  # safe inverse commit
```

To recreate the whole repo from scratch (last resort):

```bash
rm -rf ~/.openclaw/skills
mkdir -p ~/.openclaw/skills
cd ~/.openclaw/skills
git init
# then re-create each skill from your remote backup or memory files
```
