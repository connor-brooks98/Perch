# Final Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining SQLite dependency, documentation-structure, and test-resource findings, then verify and publish `production-hardening` normally.

**Architecture:** Keep runtime behavior unchanged. Document `sqlite3` as a primary Raspberry Pi host dependency, make the beginner-guide contracts structural, and make `ClipRecoveryTests` explicitly own and close all helper-created connections.

**Tech Stack:** GitHub-flavored Markdown, Python 3.11+ `unittest`, SQLite, Docker Compose, Bash

## Global Constraints

- Raspberry Pi OS Lite 64-bit remains the primary installation path.
- Install the Debian `sqlite3` CLI only in the primary Raspberry Pi guide; advanced hosts choose their platform equivalent.
- Every fenced `bash` command block in `Perch_Installation_Guide.md` must have the nearest preceding non-empty line equal to `**Run on your computer:**` or `**Run on the Raspberry Pi:**`.
- Individually preserve checkpoints for image flashing, SSH, Docker plus SQLite, repository clone, settings, model bundle, Blink authentication, preflight, service launch, and dashboard access.
- Production database code and application behavior must not change.
- No force-push, tag, release, pull request, or service launch.

---

### Task 1: Document and test the SQLite host dependency

**Files:**
- Modify: `tests/test_installation.py`
- Modify: `README.md`
- Modify: `Perch_Installation_Guide.md`

**Interfaces:**
- Consumes: existing recovery commands that invoke `sqlite3 data/db/feeder.sqlite`.
- Produces: a tested primary-host installation and verification path for the CLI.

- [x] **Step 1: Add the failing documentation contract**

Add to `InstallationContractTests`:

```python
def test_primary_pi_guide_installs_and_verifies_sqlite_cli(self) -> None:
    guide = read("Perch_Installation_Guide.md")
    documents = "\n".join([read("README.md"), guide])
    self.assertIn("sudo apt-get install -y sqlite3", guide)
    self.assertIn("sqlite3 --version", guide)
    self.assertIn("SQLite command-line utility", documents)
```

- [x] **Step 2: Run the contract and observe the intended failure**

Run:

```bash
python3 -m unittest tests.test_installation.InstallationContractTests.test_primary_pi_guide_installs_and_verifies_sqlite_cli -v
```

Expected: FAIL because the guide uses `sqlite3` without installing or verifying it.

- [x] **Step 3: Add the primary-host install and checkpoint**

In Part 2c of `Perch_Installation_Guide.md`, after installing Docker, add a separately labeled Pi command block:

```bash
sudo apt-get update
sudo apt-get install -y sqlite3
```

Extend the verification block to include:

```bash
docker --version
docker compose version
sqlite3 --version
```

Change the checkpoint to require version output from Docker, Compose, and SQLite. Explain that the SQLite command-line utility supports the inspection and manual-requeue commands later in the guide.

- [x] **Step 4: Clarify the README dependency boundary**

Before the first `sqlite3` recovery command in `README.md`, state:

```markdown
These database inspection and recovery commands use the SQLite command-line
utility installed by the primary Raspberry Pi guide. Advanced hosts must
install their operating system's equivalent `sqlite3` package.
```

- [x] **Step 5: Run the focused and documentation suites**

Run:

```bash
python3 -m unittest tests.test_installation.InstallationContractTests.test_primary_pi_guide_installs_and_verifies_sqlite_cli -v
python3 -m unittest tests.test_installation -v
```

Expected: PASS with zero failures.

---

### Task 2: Enforce beginner-guide structure

**Files:**
- Modify: `tests/test_installation.py`
- Temporarily mutate and restore: `Perch_Installation_Guide.md`

**Interfaces:**
- Consumes: the finished beginner guide and its exact command-location labels.
- Produces: structural contracts for command blocks and ten named checkpoints.

- [x] **Step 1: Add a fenced-block parser helper**

Add above `InstallationContractTests`:

```python
def bash_block_labels(document: str) -> list[str]:
    lines = document.splitlines()
    labels: list[str] = []
    for index, line in enumerate(lines):
        if line.strip() != "```bash":
            continue
        prior = index - 1
        while prior >= 0 and not lines[prior].strip():
            prior -= 1
        labels.append(lines[prior].strip() if prior >= 0 else "")
    return labels
```

- [x] **Step 2: Replace substring-only structure tests**

Keep the existing scope and placeholder assertions, but replace the weak label/checkpoint assertions with:

```python
def test_every_beginner_guide_command_block_has_a_location_label(self) -> None:
    guide = read("Perch_Installation_Guide.md")
    allowed = {"**Run on your computer:**", "**Run on the Raspberry Pi:**"}
    labels = bash_block_labels(guide)
    self.assertTrue(labels)
    self.assertTrue(all(label in allowed for label in labels), labels)

def test_beginner_guide_has_each_required_checkpoint(self) -> None:
    guide = read("Perch_Installation_Guide.md")
    required = {
        "Raspberry Pi Imager shows",
        "prompt changes after login",
        "Docker, Compose, and SQLite",
        "clone finishes without an error",
        "`.env` contains your Blink details",
        "Verified model bundle installed",
        "Authentication is accepted",
        "Container privilege, data-directory, and model inference checks passed.",
        "Perch services as started",
        "Perch dashboard opens",
    }
    for phrase in required:
        self.assertIn(phrase, guide, phrase)
```

- [x] **Step 3: Prove the structural tests detect regressions**

Using `apply_patch`, temporarily remove the `**Run on the Raspberry Pi:**` line immediately before `./scripts/download-model.sh` and change `Verified model bundle installed` to `Model installed`. Run:

```bash
python3 -m unittest \
  tests.test_installation.InstallationContractTests.test_every_beginner_guide_command_block_has_a_location_label \
  tests.test_installation.InstallationContractTests.test_beginner_guide_has_each_required_checkpoint -v
```

Expected: two failures, one identifying a missing command label and one identifying the model checkpoint. Restore both exact documentation lines with `apply_patch`.

- [x] **Step 4: Run the restored structural contracts**

Run the two-test command from Step 3.

Expected: PASS.

---

### Task 3: Close SQLite test connections deterministically

**Files:**
- Modify: `tests/test_clip_recovery.py`

**Interfaces:**
- Consumes: `db.connect(path) -> sqlite3.Connection`.
- Produces: `ClipRecoveryTests.connect()` connections owned and closed by each test case.

- [x] **Step 1: Add the failing cleanup test**

Add:

```python
def test_teardown_closes_connections_created_by_helper(self) -> None:
    case = self.__class__("test_connect_migrates_legacy_clips_table")
    case.setUp()
    conn = case.connect()
    case.tearDown()

    with self.assertRaises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
```

- [x] **Step 2: Run it and observe the intended failure**

Run:

```bash
python3 -m unittest tests.test_clip_recovery.ClipRecoveryTests.test_teardown_closes_connections_created_by_helper -v
```

Expected: FAIL because `tearDown()` currently cleans the temporary directory without closing `conn`.

- [x] **Step 3: Register and close connections**

Implement:

```python
def setUp(self) -> None:
    self.temporary = tempfile.TemporaryDirectory()
    self.db_path = Path(self.temporary.name) / "feeder.sqlite"
    self.connections: list[sqlite3.Connection] = []

def tearDown(self) -> None:
    for conn in reversed(self.connections):
        conn.close()
    self.connections.clear()
    self.temporary.cleanup()

def connect(self) -> sqlite3.Connection:
    conn = db.connect(self.db_path)
    self.connections.append(conn)
    return conn
```

Keep the legacy connection's explicit `legacy.close()`.

- [x] **Step 4: Run cleanup and warning-strict tests**

Run:

```bash
python3 -m unittest tests.test_clip_recovery -v
PYTHONWARNINGS=error::ResourceWarning python3 -m unittest tests.test_clip_recovery -v
```

Expected: both commands pass with no `ResourceWarning` output.

---

### Task 4: Full verification, review, commit, and push

**Files:**
- Verify all changed files.
- Update checkboxes in: `docs/superpowers/plans/2026-07-13-final-followups.md`

**Interfaces:**
- Consumes: Tasks 1–3 and the existing verified container stack.
- Produces: reviewed commits pushed normally from `production-hardening`.

- [x] **Step 1: Run the complete unit suite**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

Expected: all tests pass with no failures, errors, or SQLite `ResourceWarning`s.

- [x] **Step 2: Run static and Compose checks**

Run Python compilation with `PYTHONPYCACHEPREFIX` directed to `/tmp`, run `bash -n scripts/*.sh`, render base and Cloudflare Compose with non-secret environment values, and run `git diff --check`.

Expected: every command exits `0`.

- [x] **Step 3: Run the complete Docker preflight**

Use the existing ignored verified model bundle and a temporary non-secret `.env` if no private `.env` exists. Run:

```bash
./scripts/verify-install.sh --build
```

Expected final line:

```text
Container privilege, data-directory, and model inference checks passed.
```

Remove a temporary `.env` afterward and confirm no test containers remain.

- [x] **Step 4: Review and commit**

Review `git diff`, `git diff --check`, and `git status --short`. Commit only the intended follow-up files and completed plan:

```bash
git add README.md Perch_Installation_Guide.md tests/test_installation.py tests/test_clip_recovery.py docs/superpowers/plans/2026-07-13-final-followups.md
git commit -m "docs: close final installation follow-ups"
```

- [x] **Step 5: Verify the committed state**

Run the complete unit suite again and confirm `git status --short` is empty.

Expected: all tests pass and the worktree is clean.

- [x] **Step 6: Push normally**

Inspect `git remote -v`, the current branch, and upstream. Fetch the remote and confirm the push is a normal fast-forward; do not rebase or rewrite history automatically. Then run:

```bash
git push -u origin production-hardening
```

Expected: Git reports a successful update to the configured GitHub remote. Do not force-push.
