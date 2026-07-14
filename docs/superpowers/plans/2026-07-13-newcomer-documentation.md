# Newcomer Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the README an approachable project landing page and the installation guide the single authoritative, beginner-safe Raspberry Pi setup procedure.

**Architecture:** Separate documentation by reader intent. `README.md` provides orientation, support boundaries, an experienced-user quick start, success signals, and symptom-based troubleshooting; `Perch_Installation_Guide.md` owns the complete linear installation flow and explains every command for first-time users.

**Tech Stack:** GitHub-flavored Markdown, Python 3.11 `unittest`, Docker Compose preflight

## Global Constraints

- Raspberry Pi 5 with Raspberry Pi OS Lite 64-bit is the primary and tested path.
- Other 64-bit hosts that run Linux Docker containers are advanced installations, not guaranteed platforms.
- `Perch_Installation_Guide.md` is the single authoritative step-by-step procedure.
- Preserve the Blink subscription requirement and dedicated-account recommendation.
- Preserve literal single-quoted bcrypt hashes and never tell users to double `$` characters.
- MobileNetV2 remains the stable runtime; ONNX remains experimental and unavailable.
- Preserve the transactional model path `classifier/model/current/`.
- Do not change application behavior or dependencies.
- Preserve unrelated local changes; do not commit or push.

---

### Task 1: Documentation contract for audience routing and platform scope

**Files:**
- Modify: `tests/test_installation.py`

**Interfaces:**
- Consumes: `read(relative_path: str) -> str` from `tests/test_installation.py`.
- Produces: regression assertions that define the README/guide roles and supported-platform wording.

- [ ] **Step 1: Add failing audience and platform assertions**

Add these methods to `InstallationContractTests`:

```python
def test_readme_routes_first_time_installers_to_the_authoritative_guide(self) -> None:
    readme = read("README.md")
    guide = read("Perch_Installation_Guide.md")
    self.assertIn("# Perch", readme)
    self.assertIn("[first-time installation guide](Perch_Installation_Guide.md)", readme)
    self.assertIn("single authoritative", guide)

def test_docs_state_the_supported_platform_boundary(self) -> None:
    documents = "\n".join([read("README.md"), read("Perch_Installation_Guide.md")])
    self.assertIn("primary and tested installation path", documents)
    self.assertIn("64-bit machines that run Linux Docker containers", documents)
    self.assertIn("advanced installation", documents)
    self.assertNotIn("runs unchanged on any", documents.lower())
```

- [ ] **Step 2: Run the new assertions and verify the intended failure**

Run:

```bash
python3 -m unittest \
  tests.test_installation.InstallationContractTests.test_readme_routes_first_time_installers_to_the_authoritative_guide \
  tests.test_installation.InstallationContractTests.test_docs_state_the_supported_platform_boundary -v
```

Expected: both tests fail because the README is still titled “Smart Bird Feeder — backend,” lacks the prominent guide link, and overstates host portability.

- [ ] **Step 3: Keep the failing tests for Task 2**

Do not weaken copy-sensitive assertions to match old text. Task 2 supplies the documented contract.

---

### Task 2: Rebuild the README as the project landing page

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: audience and platform assertions from Task 1.
- Produces: the primary GitHub landing page and an experienced-user route into the authoritative guide.

- [ ] **Step 1: Replace the opening and navigation**

Use this heading and opening structure:

```markdown
# Perch

Perch turns a Blink camera and a home server into a private, locally powered
bird-identification feeder. It downloads motion clips, identifies visiting
birds on your own hardware, and serves a password-protected field-log dashboard.

> **Installing Perch for the first time?** Follow the
> [first-time installation guide](Perch_Installation_Guide.md). It assumes no
> Linux, Docker, or command-line experience and uses the primary Raspberry Pi 5
> setup path.

## What to expect

- Bird identification runs locally; clips are not sent to an AI API.
- Raspberry Pi 5 with Raspberry Pi OS Lite 64-bit is the primary and tested installation path.
- Other 64-bit machines that run Linux Docker containers may work as an advanced installation.
- A dedicated Blink account and active Blink subscription are currently required.
- The dashboard works on a home network by default; internet access is optional.
```

Remove the claim that the Compose project moves to any other 64-bit Linux host “unchanged.” Keep the pipeline diagram after this beginner-facing orientation.

- [ ] **Step 2: Make the quick start explicitly advanced**

Rename `First-time setup` to `Experienced-user quick start` and begin it with:

```markdown
This section is for readers already comfortable with SSH, environment files,
and Docker Compose. Everyone else should use the
[first-time installation guide](Perch_Installation_Guide.md).
```

Keep only the canonical path: configure `.env`, generate bcrypt, run `download-model.sh`, run Blink authentication, run `verify-install.sh --build`, and start Compose. Remove explanatory detail that belongs in the guide, but retain exact commands and the literal-dollar warning.

- [ ] **Step 3: Add concrete success criteria**

Immediately after the quick start add:

```markdown
## How to know it worked

1. `./scripts/verify-install.sh --build` ends with
   `Container privilege, data-directory, and model inference checks passed.`
2. `docker compose ps` shows `puller`, `classifier`, and `web` running.
3. `http://<pi-ip>:8080` shows the Perch login page. Replace `<pi-ip>` with the
   Raspberry Pi's local address; do not type the angle brackets.
4. After login, an empty dashboard is normal until Blink records a new motion clip.
```

- [ ] **Step 4: Add symptom-based troubleshooting**

Add a `Troubleshooting` table before technical notes with at least these rows:

| Symptom | First check |
|---|---|
| Docker permission or daemon error | Run `docker info`; reconnect after joining the `docker` group and confirm Docker is running. |
| Preflight says `.env` is missing or unsafe | Copy `.env.example`, fill it in, and run `chmod 600 .env`. |
| Model files are missing or invalid | Run `./scripts/download-model.sh`; do not copy one model-bundle file by itself. |
| Blink login or 2FA fails | Confirm the dedicated account works in Blink, wait after repeated attempts, then rerun `auth_setup.py`. |
| Dashboard does not open | Run `docker compose ps`, then try the Pi's local IP on port `8080`. |
| Dashboard opens but has no birds | Confirm Blink recorded a subscribed cloud clip, then inspect `docker compose logs classifier`. |
| A clip reached terminal error | Correct the cause, then use the documented manual requeue command. |

- [ ] **Step 5: Organize remaining material by reader intent**

Keep sections in this order after troubleshooting:

```markdown
## Everyday operation
## Configuration reference
## Backups and updates
## Remote access (optional)
## Security and privacy
## Architecture and repository map
## Model policy and known limitations
```

Move existing content rather than duplicating it. Define SSH, Docker Compose, and TFLite on first use. Keep MobileNetV2/ONNX details in the final technical section.

- [ ] **Step 6: Run the Task 1 assertions**

Run the two-test command from Task 1.

Expected: PASS.

---

### Task 3: Make the installation guide linear and authoritative

**Files:**
- Modify: `Perch_Installation_Guide.md`
- Modify: `tests/test_installation.py`

**Interfaces:**
- Consumes: canonical commands and success output from `scripts/download-model.sh` and `scripts/verify-install.sh`.
- Produces: one beginner-safe Raspberry Pi setup path with observable checkpoints.

- [ ] **Step 1: Add failing guide-quality assertions**

Add:

```python
def test_beginner_guide_is_linear_and_has_success_checkpoints(self) -> None:
    guide = read("Perch_Installation_Guide.md")
    self.assertIn("single authoritative", guide)
    self.assertIn("Primary and tested setup", guide)
    self.assertIn("Checkpoint:", guide)
    self.assertIn("Container privilege, data-directory, and model inference checks passed.", guide)
    self.assertNotIn("Option B", guide)
    self.assertNotIn("Option C", guide)

def test_beginner_guide_explains_command_locations_and_placeholders(self) -> None:
    guide = read("Perch_Installation_Guide.md")
    self.assertIn("Run on your computer", guide)
    self.assertIn("Run on the Raspberry Pi", guide)
    self.assertIn("Do not type the angle brackets", guide)
```

- [ ] **Step 2: Run the assertions and verify the intended failure**

Run:

```bash
python3 -m unittest \
  tests.test_installation.InstallationContractTests.test_beginner_guide_is_linear_and_has_success_checkpoints \
  tests.test_installation.InstallationContractTests.test_beginner_guide_explains_command_locations_and_placeholders -v
```

Expected: FAIL because the guide still presents three model-install options and lacks consistent checkpoint/location labels.

- [ ] **Step 3: Establish scope at the top of the guide**

After the title, add:

```markdown
This is Perch's single authoritative first-time installation guide. It follows
the primary and tested setup: a Raspberry Pi 5 running Raspberry Pi OS Lite
64-bit. No Linux, Docker, Git, or command-line experience is assumed.

Other 64-bit machines that run Linux Docker containers may work, but those are
advanced installations and can require different permission, networking, or
inference dependencies.
```

- [ ] **Step 4: Label command locations and checkpoints consistently**

Before every command block, use one of these exact labels:

```markdown
**Run on your computer:**
```

```markdown
**Run on the Raspberry Pi:**
```

After flashing, SSH connection, Docker installation, repository clone,
configuration, model installation, Blink authentication, preflight, launch,
and dashboard access, add a short paragraph beginning `**Checkpoint:**` that
states the concrete output or visible state that proves the step completed.

- [ ] **Step 5: Remove unsupported model-install branches**

Delete model-install Options B and C. Keep `./scripts/download-model.sh` as the
only beginner path and explain that it verifies and promotes model plus labels
as one bundle. Preserve the upgrade instruction to rerun the helper for the
`classifier/model/current/` migration.

- [ ] **Step 6: Explain placeholders at first use**

When `<username>`, `<hostname>`, `<pi-ip>`, or `<path>` first appears, state:

```markdown
Text inside angle brackets is a placeholder. Replace it with your own value;
do not type the angle brackets themselves.
```

Do not use `pi` as though it is guaranteed to be the configured username.

- [ ] **Step 7: Align launch success text with the real preflight**

Replace the weaker “Container images built successfully” stopping point with
the final required line:

```text
Container privilege, data-directory, and model inference checks passed.
```

Explain that the initial dashboard may be empty until a new subscribed Blink
cloud clip is recorded and processed.

- [ ] **Step 8: Run the guide-quality assertions**

Run the two-test command from Step 2.

Expected: PASS.

---

### Task 4: Link integrity and final verification

**Files:**
- Modify: `tests/test_installation.py`
- Verify: `README.md`
- Verify: `Perch_Installation_Guide.md`

**Interfaces:**
- Consumes: final Markdown files from Tasks 2 and 3.
- Produces: repeatable local-link validation and fresh end-to-end evidence.

- [ ] **Step 1: Add a local Markdown-link test**

Add `import re` near the test module imports, then add:

```python
def test_primary_docs_have_no_broken_local_markdown_links(self) -> None:
    for relative_path in ("README.md", "Perch_Installation_Guide.md"):
        document = read(relative_path)
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", document):
            if "://" in target or target.startswith("#"):
                continue
            path_text = target.split("#", 1)[0]
            self.assertTrue(
                (ROOT / path_text).exists(),
                f"{relative_path} links to missing local path {target}",
            )
```

- [ ] **Step 2: Run the documentation contract suite**

Run:

```bash
python3 -m unittest tests.test_installation -v
```

Expected: every installation and documentation contract passes.

- [ ] **Step 3: Run the complete unit suite**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests pass with zero failures or errors.

- [ ] **Step 4: Run static checks**

Run:

```bash
bash -n scripts/*.sh
docker compose config -q
git diff --check
```

Expected: each command exits `0` with no syntax, Compose, or whitespace errors.
Use a temporary non-secret `.env` only if Compose requires values, and remove it afterward.

- [ ] **Step 5: Run the real container preflight**

With a private real `.env` or a temporary non-secret verification `.env`, run:

```bash
./scripts/verify-install.sh --build
```

Expected final line:

```text
Container privilege, data-directory, and model inference checks passed.
```

Remove any temporary `.env`, confirm no test containers remain, and do not launch the Blink-connected services with fake credentials.

- [ ] **Step 6: Review worktree scope**

Run:

```bash
git status --short
git diff -- README.md Perch_Installation_Guide.md tests/test_installation.py docs/superpowers/specs/2026-07-13-newcomer-documentation-design.md docs/superpowers/plans/2026-07-13-newcomer-documentation.md
```

Expected: only intentional documentation-contract changes from this pass plus the user's pre-existing local work. No commit or push occurs.
