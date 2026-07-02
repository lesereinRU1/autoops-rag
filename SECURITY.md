# Security Policy

## Supported version

Security fixes are applied to the latest commit on the default branch.

## Reporting a vulnerability

Do not open a public issue containing credentials, private documents, internal hostnames, or exploit details. Contact the repository owner privately through GitHub instead.

## Secrets and private data

- Keep real credentials only in the ignored local `.env` file or a deployment secret manager.
- Never commit raw manuals, production traces, model caches, Qdrant data, customer documents, or screenshots containing tokens.
- Run `python scripts/check_public_release.py --history` before changing the repository to public.
- Revoke and rotate a credential immediately if it appears in Git history, logs, screenshots, issues, or pull requests.

The application binds its published ports to `127.0.0.1` by default. Authentication, TLS termination, and an external rate limiter are required before exposing it to an untrusted network.
