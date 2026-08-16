# Bot Ownership Boundary

This repository owns the complete Dududa Bot runtime and no general-purpose
site infrastructure.

## Included

- AstrBot runtime image and configuration bootstrap.
- NapCat QQ adapter and local persistent login directories.
- Dududa Core and Sub2API Readonly owned plugins.
- Reply Polish source as a default-off Dududa 1.0 LONG-only compatibility layer.
- Target Talk source as historical migration/rollback material; it is not mounted by
  the Dududa 2.0 default Compose path.
- Exact third-party plugin installation metadata. Automatic Meme Manager, Reread and
  PokePro behavior is not part of the Dududa 2.0 default installation.
- The Iris user/group memory-isolation patch.
- The `icourse-mcp` service and its local cache schema.
- Persona and MCP templates that contain no account or provider credentials.

## External

- OpenAI-compatible model provider, including its account database and keys.
- Caddy, Authelia, Cloudflare Tunnel and public DNS.
- PostgreSQL, Redis, Sub2API and outbound proxy services.
- Host firewall, backups and monitoring.

The model provider is configured through AstrBot runtime data. The gateway may
reach the Bot through the stable Docker network aliases in `compose.yml`.

## Persistent Data

```text
data/
├── astrbot/
│   ├── data_v4.db
│   ├── cmd_config.json
│   ├── config/
│   ├── plugin_data/
│   └── plugins/
└── napcat/
    ├── config/
    └── ntqq/
```

Everything in this tree is private runtime state. It can include conversations,
memories, administrator identifiers, provider credentials, OneBot tokens and QQ
login state. It is excluded by `.gitignore` and must be backed up separately.

## Memory Isolation

The pinned Iris base commit receives two local changes during installation:

1. L2 retrieval discards memories explicitly owned by another user.
2. L3 graph retrieval uses the group-aware detailed search when a group ID is
   available.

CI checks that both guards remain in the patch. A lock update must reapply and
test the patch before merge.
