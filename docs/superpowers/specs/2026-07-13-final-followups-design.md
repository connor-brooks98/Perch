# Final Follow-ups Design

## Goal

Close the three non-blocking findings from the newcomer-documentation review,
verify the complete local build again, and publish the reviewed
`production-hardening` branch without force-pushing.

## SQLite recovery dependency

The primary Raspberry Pi installation path will install the Debian `sqlite3`
command-line package. The installation guide will include it in the Pi setup
commands and verify availability with `sqlite3 --version`. The README and guide
will state that this utility powers direct detection inspection and terminal
clip requeue commands. Advanced non-Debian Docker hosts remain responsible for
installing an equivalent SQLite CLI through their operating system.

This keeps recovery commands readable for beginners and avoids adding a custom
recovery script or coupling database maintenance to a running Perch container.

## Structural documentation contracts

Installation tests will parse the beginner guide rather than checking only for
global substrings. Each fenced command block must have the closest preceding
non-empty line equal to either `**Run on your computer:**` or
`**Run on the Raspberry Pi:**`. The tests will also assert the named checkpoint
milestones individually: image flashing, SSH, Docker plus SQLite, repository
clone, settings, model bundle, Blink authentication, preflight, service launch,
and dashboard access.

Tests will first be demonstrated failing against a controlled mutation or a
new unmet contract, then pass against the corrected guide.

## SQLite test cleanup

`ClipRecoveryTests` will own every connection created through its `connect()`
helper. The helper will register each connection and `tearDown()` will close
all registered connections before cleaning the temporary directory. Direct
legacy connections will continue to be explicitly closed where created.

The clip-recovery suite will be run with `ResourceWarning` promoted to an error
so leaked SQLite connections fail deterministically. Normal behavior and
database production code will not change.

## Verification and publication

The implementation will run focused red/green tests, the complete unit suite,
Python and shell checks, base and Cloudflare Compose rendering, Markdown-link
checks, and `./scripts/verify-install.sh --build` with a temporary non-secret
configuration. Temporary credentials, containers, and test artifacts will be
removed afterward.

After a final diff review, changes will be committed on
`production-hardening`. The branch will be pushed normally to its configured
GitHub remote. No force-push, tag, release, pull request, or service launch is
part of this work.

## Out of scope

- No application runtime, schema, dependency, or model changes.
- No custom database-maintenance helper.
- No support promise for non-Debian advanced hosts.
- No history rewriting or force-pushing.
