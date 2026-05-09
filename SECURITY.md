# Security Policy

## Supported Surface

This repository contains the public OnlineWorker app surface.

Security-sensitive areas include:

- Telegram bot token handling
- local app configuration and `.env` loading
- packaged app installation flow
- provider process spawning and local IPC

## Reporting a Vulnerability

Do not open public issues for unpatched security vulnerabilities.

Use a private reporting path:

1. Prefer the Git hosting platform's private vulnerability reporting feature if
   it is enabled.
2. If private reporting is not available, contact the maintainer through an
   existing private channel.

Include:

- affected version or commit
- impact summary
- reproduction steps
- environment details
- proof-of-concept only if necessary

## What to Expect

After acknowledgement, the goal is to:

1. reproduce the issue
2. assess impact and scope
3. prepare a fix
4. publish the fix and any required user guidance

Response times are best-effort and depend on maintainer availability.
