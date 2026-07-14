# Newcomer Documentation Design

## Goal

Make Perch approachable to people with any level of technical experience while
keeping setup instructions accurate, maintainable, and easy to troubleshoot.

## Audience and support boundary

Raspberry Pi 5 running Raspberry Pi OS Lite 64-bit is the primary and tested
installation path. Other 64-bit machines that run Linux Docker containers may
work, but they are advanced installations rather than guaranteed platforms.
The documentation must not imply support for every device that can run some
form of Docker.

## Documentation roles

`README.md` is the project landing page. It explains what Perch does, shows the
expected result, states requirements and limitations, directs beginners to the
installation guide, provides a concise quick start for experienced users, and
covers common operations and failures.

`Perch_Installation_Guide.md` is the single authoritative step-by-step setup
procedure. It assumes no command-line or Docker experience, follows one tested
Raspberry Pi path, explains where each command is run, and gives an observable
success signal after each major stage.

The README may summarize installation commands, but it must link to the guide
instead of duplicating detailed explanations or alternative transfer methods.

## README structure

The README will use this order:

1. Project name, plain-language purpose, and expected user experience.
2. A prominent first-time installer link to the full guide.
3. A short status and limitations section covering Blink subscription, primary
   hardware, Linux-container support, local inference, and remote access.
4. A concise architecture overview and repository map for technical readers.
5. An experienced-user quick start with links back to detailed guide sections.
6. Clear success criteria: preflight output, running services, dashboard URL,
   and what an initial empty dashboard means.
7. Everyday operation and configuration controls.
8. A symptom-based troubleshooting table with the first command or check to
   perform and a link to fuller guidance where appropriate.
9. Backup, updating, remote access, security, and known limitations.
10. Technical model policy, with MobileNetV2 stable and ONNX experimental.

## Beginner-writing rules

- Define Docker, SSH, Compose, TFLite, and other necessary terms on first use.
- State whether a command runs on the user's computer or on the Raspberry Pi.
- Use one command per line when order matters.
- Put expected output or a concrete success check after important commands.
- Explain placeholders such as `<pi-ip>` and never expect them to be pasted
  literally.
- Prefer one recommended path; label alternatives as advanced or optional.
- Keep secrets out of examples and preserve the literal bcrypt-dollar rule.
- Avoid jokes, relationship-specific language, and assumptions about prior
  Linux, networking, Git, or Docker knowledge.

## Troubleshooting coverage

The README and guide together must cover:

- Docker daemon unavailable or permission denied.
- Preflight failures, including missing `.env`, permissions, and model files.
- Blink authentication, 2FA, subscription, camera-name, and expired-session
  problems.
- Dashboard unreachable locally, authentication failure, and remote-access
  expectations.
- No detections yet, camera connectivity or battery problems, and classifier
  logs.
- Failed clips, automatic retry behavior, and manual requeue.
- Upgrade migration to the transactional `classifier/model/current` bundle.

## Verification

Documentation contract tests will assert the beginner-guide link, supported
platform wording, success signals, troubleshooting topics, transactional model
path, stable MobileNetV2 policy, and experimental ONNX boundary. Markdown links
and referenced local paths will be checked. The complete unit suite and Docker
preflight will be rerun after the documentation changes.

## Out of scope

This pass will not add a graphical installer, support new operating systems,
change application behavior, introduce ONNX, publish releases, commit changes,
or push to GitHub.
