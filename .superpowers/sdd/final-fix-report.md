# Final newcomer-documentation fix report

## Outcome

All Important findings from the final newcomer-documentation review were fixed
and covered by focused regression contracts. The implementation commit is
`f8e01354069682369d906d9a20465764cd39ed93` (`docs: correct newcomer security
guidance`). This report is committed separately so it can record that immutable
implementation hash.

## TDD evidence

### Red

After adding the four focused documentation-contract tests and before changing
the documentation, the exact command was:

```bash
python3 -m unittest tests.test_installation -v
```

Result: exit `1`; 25 tests ran, with 4 expected failures:

- `test_docs_hash_dashboard_password_at_a_hidden_interactive_prompt`
- `test_docs_recommend_private_tailscale_serve_for_remote_access`
- `test_docs_require_outbound_internet_but_not_remote_dashboard_access`
- `test_readme_recommends_a_dedicated_account_but_requires_subscription`

The failures were caused by the old Funnel command, the plaintext password
argument, the optional-internet claim, and the account/subscription wording.

### Green

After the minimal documentation fixes, the exact command was repeated:

```bash
python3 -m unittest tests.test_installation -v
```

Result: exit `0`; 25 tests ran and all passed.

## Official documentation verification

Verified on 2026-07-13 against these official references:

- Tailscale Serve feature documentation:
  <https://tailscale.com/docs/features/tailscale-serve>
- Tailscale Serve CLI reference:
  <https://tailscale.com/docs/reference/tailscale-cli/serve>
- Tailscale Funnel feature documentation:
  <https://tailscale.com/docs/features/tailscale-funnel>
- Caddy `hash-password` CLI reference:
  <https://caddyserver.com/docs/command-line#caddy-hash-password>

The Serve feature documentation defines Serve as tailnet-only and shows a
local port as the target (`tailscale serve 3000`). The current CLI reference
accepts `tailscale serve [flags] <target>`, documents `--bg` as persistent
background mode, and accepts a bare local port target. Therefore the guides use:

```bash
sudo tailscale serve --bg 8080
```

The Funnel documentation states that Funnel routes broader-internet traffic to
a local service and is accessible even to people who do not use Tailscale. Both
guides now explicitly contrast public Funnel with private Serve and do not
present `tailscale funnel 8080` as the default phone-access path.

Caddy documents `--plaintext` as optional: when omitted, it reads the password
from standard input, and with a controlling TTY the input is not echoed. Both
guides now use the requested interactive container command:

```bash
docker run --rm -it caddy:2.11.4-alpine caddy hash-password
```

They tell the user to enter the password at the hidden prompt and to preserve
the generated bcrypt hash literally inside single quotes without doubling `$`.

## Files changed

- `README.md`
  - Recommends a dedicated Blink account while separately requiring an active
    Blink subscription.
  - Preserves the personal-login session-conflict rationale.
  - Replaces the optional-internet claim with the outbound-internet boundary.
  - Uses hidden interactive Caddy password entry.
  - Recommends persistent, private Tailscale Serve and warns that Funnel is
    public.
- `Perch_Installation_Guide.md`
  - States that remote dashboard access is optional while outbound internet is
    needed for Blink and installation downloads.
  - Uses hidden interactive Caddy password entry.
  - Recommends persistent, private Tailscale Serve and warns that Funnel is
    public.
- `tests/test_installation.py`
  - Adds contracts for no default Funnel command, private Serve wording,
    interactive password hashing, account recommendation versus subscription
    requirement, session-conflict rationale, and outbound internet.
- `.superpowers/sdd/final-fix-report.md`
  - Records this audit trail.

## Full verification

The host complete-suite command was first run exactly as follows:

```bash
python3 -m unittest discover -s tests -v
```

Result: exit `1`; 39 tests ran and two test modules failed to import because the
host Python lacked Pillow (`ModuleNotFoundError: No module named 'PIL'`).

An isolated environment was then created around the bundled CPython 3.13.5
runtime, with only the host-test dependencies from
`classifier/requirements.txt`:

```bash
UV_CACHE_DIR=/private/tmp/perch-uv-cache uv venv /private/tmp/perch-final-fix-venv --python /Users/connor/.local/share/uv/python/cpython-3.13.5-macos-aarch64-none/bin/python3.13
UV_CACHE_DIR=/private/tmp/perch-uv-cache uv pip install --python /private/tmp/perch-final-fix-venv/bin/python 'numpy>=1.24,<2' 'Pillow>=10.0,<13'
/private/tmp/perch-final-fix-venv/bin/python -m unittest discover -s tests -v
```

The environment resolved NumPy 1.26.4 and Pillow 12.3.0. Result: exit `0`; 45
tests ran and all passed. The run emitted the pre-existing unclosed SQLite
`ResourceWarning` messages; they were intentionally not addressed.

The whitespace check was:

```bash
git diff --check
```

Result: exit `0`, with no output.

## Cleanup and repository scope

The isolated `/private/tmp/perch-final-fix-venv` and
`/private/tmp/perch-uv-cache` directories were removed after the full run. No
global packages were installed, no external state was changed, and nothing was
pushed. Work was confined to the requested worktree plus the temporary test
environment.

## Self-review

- Re-read every Important finding against both primary documents.
- Confirmed neither document contains `tailscale funnel 8080` or
  `hash-password --plaintext`.
- Confirmed both documents contain the persistent private Serve command, hidden
  prompt guidance, literal single-quoted bcrypt handling, and the outbound
  internet boundary.
- Confirmed README distinguishes the strongly recommended account from the
  required subscription and retains the session-conflict explanation.
- Reviewed the final diff for unrelated changes; only the two documents, the
  focused contracts, and this report changed.

## Deferred Minor findings and concerns

The two explicitly deferrable Minor review items remain for later work:

- Documenting/installing the host `sqlite3` utility used by manual commands.
- Replacing substring-based milestone checks with stronger structural parsing.

The only observed test concern is the pre-existing SQLite `ResourceWarning`
output noted above. It does not fail the suite and was outside this task's scope.
