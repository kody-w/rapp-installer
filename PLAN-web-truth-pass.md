# PLAN: Web truth pass — the public site contradicts the shipped product

**Rank: 3 of 5.**

## Goal

Every public surface (landing page, release notes, README, skill.md) tells the truth
about v0.6.3, no live 404s, and root↔docs drift becomes mechanically impossible to ship.

The landing page is the entire acquisition funnel; release-notes.html is three releases
behind and README/skill.md instruct users to use a feature that was deleted in v0.1.0.

## Files to touch

- `release-notes.html` (root only — NOT mirrored to docs/, served from the repo, but
  keep it consistent anyway)
- `index.html` (root) **and** `docs/index.html` (byte-identical mirror — see edge cases)
- `README.md`
- `skill.md`
- `docs/tutorial.html` (orphan — delete)
- `tests/test_installer.sh` (add drift guard)

## Current state (verified on main @ v0.6.3, 2026-07-06)

1. **release-notes.html:96** — newest entry is v0.6.0 ("Latest" badge), but main ships
   **0.6.3** (`rapp_brainstem/VERSION`), with tags `brainstem-v0.6.1`, `brainstem-v0.6.2`,
   `brainstem-v0.6.3` already pushed. Three releases invisible to users.
2. **index.html:394** (root and docs/ identically) —
   `<a href="rapp_brainstem/README.md">Brainstem Docs</a>`. GitHub Pages serves from
   `docs/`, and `docs/rapp_brainstem/` does not exist → **live 404 today** on
   kody-w.github.io/rapp-installer.
3. **README.md:88** — "The chat UI has a Sources panel — paste any GitHub repo URL…"
   and **README.md:147** — API table row `| /repos | GET | ...`. The Sources panel and
   all `/repos/*` endpoints were **removed in v0.1.0** (release-notes.html:159 documents
   the removal; blog.html:243 is literally titled "Why We Killed Remote Agents").
4. **skill.md:151** — tells onboarding users to "Open the Sources panel" (same dead feature).
5. **Model wording drift** — README.md:113, skill.md:235 and the landing page Tier-2 copy
   say "Azure OpenAI (GPT-4o)", but `azuredeploy.json:37/:52` now defaults to
   `gpt-5.2-chat` (see PLAN-azure-tier2-model-version.md). Also the local default is no
   longer plain gpt-4o — it auto-selects the highest Claude Sonnet (v0.6.2).
6. **Tier-2 naming split** — landing page `index.html:299` calls Tier 2 "The Hippocampus"
   (CommunityRAPP path), while README.md:102, skill.md:172 and
   `.github/copilot-instructions.md` call Tier 2 "The Spinal Cord" (direct Azure ARM
   path). These are genuinely **two different paths** sharing one label.
7. **docs/tutorial.html** — 10KB orphan; zero inbound links anywhere in the repo
   (superseded by the external Training Quest link).
8. **Drift mechanics** — `docs/` holds byte-identical copies of `index.html`,
   `install.sh`, `install.command`, `install.cmd` that must be manually re-copied after
   every root edit. They are in sync today, but nothing enforces it. Note the two
   channels: macOS one-liner pulls from Pages (`docs/install.sh`), Windows one-liner
   pulls from `raw.../main/install.ps1` — and `install.ps1` intentionally has no docs/
   copy.

## Implementation order

1. **Release notes.** Add three entries above the v0.6.0 block in `release-notes.html`
   (copy the existing entry markup exactly; move the "Latest" badge to 0.6.3):
   - **v0.6.1** — minimal default agents: removed LearnNew from the bundled set
     (commit `ffdbf70`).
   - **v0.6.2** — Windows compatibility (dep-check arg-split, pip path quoting, UTF-8
     file I/O `2d509b4`), web-UI UTF-8 mojibake fix + honest origin-correct installer
     upgrades (`3ccabde`), model picker now only offers models that support
     /chat/completions (`7f2ec6d`), auto-selects the highest available Claude Sonnet
     (`5cf4b74`), pearl-pass stability polish + safe-release preflight harness
     (`7e38cfd`).
   - **v0.6.3** — bootstraps pip when the found Python has none (Windows corp images)
     (`73a8837`, `3abfc5a`).
   Pull exact wording from `git log` / `RELEASING.md`; do not invent features.
2. **Fix the 404.** In root `index.html:394` change the href to
   `https://github.com/kody-w/rapp-installer/tree/main/rapp_brainstem#readme`
   (absolute GitHub URL works from any origin).
3. **Kill the ghost feature.** README.md:88 — replace the Sources-panel paragraph with
   the real current mechanism (drop `*_agent.py` files into `~/.brainstem/src/rapp_brainstem/agents/`,
   hot-reloaded per request). README.md:147 — delete the `/repos` row. skill.md:151 —
   replace the Sources-panel bullet with the same agents-directory instruction.
4. **Model wording.** README.md:113 and skill.md:235: change "GPT-4o" to "the model you
   select (default gpt-5.2-chat)" for the Azure tier. Anywhere the local tier says the
   default model is gpt-4o, say "auto-selects the best available Claude Sonnet, falling
   back to gpt-4o".
5. **Tier-2 naming.** Keep "The Hippocampus" as the landing-page section name for the
   CommunityRAPP path, but retitle the Advanced "Deploy to Azure" sub-block inside it
   (near `index.html:333`) to "Spinal Cord — direct Azure deploy (ARM)". In README.md
   and skill.md add one clarifying sentence: Hippocampus = CommunityRAPP multi-project
   path; Spinal Cord = single ARM deployment; both are Tier 2. Do not rename anything else.
6. **Delete `docs/tutorial.html`.**
7. **Mirror.** After ALL root edits: `cp index.html docs/index.html` (install.sh,
   install.command, install.cmd untouched by this plan — verify with diff anyway).
8. **Drift guard.** Append to `tests/test_installer.sh` (follow its existing
   check/pass/fail helper style) a block that runs
   `diff -q index.html docs/index.html`, `diff -q install.sh docs/install.sh`,
   `diff -q install.command docs/install.command`, `diff -q install.cmd docs/install.cmd`
   and fails with "root and docs/ have drifted — copy root files into docs/" on any
   mismatch. `tests/test_installer.sh` is invoked by RELEASING.md step 2 and by the
   preflight, so drift now blocks release.

## Edge cases a weaker model would miss

- **Editing root `index.html` without re-copying to `docs/` ships nothing** — Pages
  serves `docs/`. Conversely, editing only `docs/` gets silently clobbered on the next
  sync. Always edit root, then copy. (There are TWO other index.html files:
  `rapp_brainstem/index.html` is the server chat UI, `docs/index.html` is the mirror —
  only root `index.html` is the landing page source of truth.)
- **release-notes.html's "Latest" badge** is markup on the v0.6.0 entry — move it, don't
  duplicate it.
- **Don't renumber history**: the changelog intentionally jumps v0.6.0 → v0.1.0
  (0.2–0.5 were never written up; blog.html:120 references v0.5.4). Leave the gap;
  only prepend.
- **skill.md is consumed by LLMs** (Moltbook onboarding skill with pause points) —
  keep its YAML frontmatter and step numbering intact; only edit the referenced bullet
  text, or downstream automation breaks.
- **`install.ps1` has no docs/ mirror on purpose** (Windows one-liner uses raw main).
  Do not "helpfully" add one — that would create a fifth file to keep in sync and the
  Pages URL for it is referenced nowhere.
- **tests/test_installer.sh greps for content in these files** (branding, one-liner
  strings, tier keywords). After editing index.html/README/skill.md, run it — if a grep
  fails, reconcile the check, don't delete it.

## Acceptance criteria

1. `bash tests/test_installer.sh` passes, including the new drift guard.
2. `diff index.html docs/index.html` is empty; same for the three installer files.
3. `grep -rn "Sources panel\|/repos" README.md skill.md` → no hits (except, if present,
   historical mentions in release-notes/blog which must stay).
4. `grep -n "v0.6.3" release-notes.html` → hit with the Latest badge; v0.6.1 and v0.6.2
   entries exist.
5. `grep -rn 'rapp_brainstem/README.md' index.html docs/index.html` → only the absolute
   github.com URL remains.
6. Post-release (after the maintainer merges to main): `curl -s https://kody-w.github.io/rapp-installer/ | grep -c "github.com/kody-w/rapp-installer/tree/main/rapp_brainstem"`
   ≥ 1, and the old relative link 404 is gone.
7. Branch pushed; **no push to main**.
