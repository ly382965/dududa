# Security Policy

Report vulnerabilities privately to the repository owner before opening a
public issue. Include the affected component, reproduction steps and expected
impact. Do not include real QQ identifiers, conversations or credentials.

## Secrets

The following must never be committed:

- `.env` files other than `.env.example`
- Provider API keys, WebUI passwords, JWT or OneBot tokens
- Cookies, QQ login state and NapCat passkeys
- SSH, TLS or signing private keys
- AstrBot databases, memory stores, attachments and audit logs
- Course cache databases and exported datasets

Rotate a credential immediately if it appears in a commit, then remove it from
all reachable Git history. Deleting it only in a later commit is insufficient.

## Runtime Hardening

Management ports bind to loopback by default. Keep TLS verification enabled,
protect any public gateway independently, and retain the Iris memory-isolation
patch unless an audited upstream release provides equivalent behavior.
