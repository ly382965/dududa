# USTC Campus MCP

One implementation package exposes three independently registered, read-only
MCP servers:

- `academic`: public semester, lesson, exam and teaching-calendar queries;
- `curriculum`: bounded queries over the public, unofficial curriculum research
  snapshot at `https://docs.mmdustc.top/curriculum/data/`;
- `young`: second-class activity queries through the pinned `pyustc` adapter.

Run one server over stdio:

```bash
python run_ustc_mcp.py --service academic
python run_ustc_mcp.py --service curriculum
python run_ustc_mcp.py --service young
```

`curriculum` never calls the live academic system. Its source currently covers
the 2015-2026 cohorts from the 2026-08-02 research snapshot. Course identity is
the exact course code; results are research evidence, not graduation-audit
decisions.

`young` requires the existing USTC CAS username/password SecretRefs. The local
deployment reuses the host's `ustc-catalog-crawler/credentials.toml` as a
read-only mount; the MCP Console resolves its two values and injects them only
into the `ustc-young` child process. `USTC_CAS_USR` and `USTC_CAS_PWD` remain
available for deployments backed by an environment secret store. Credentials
are never committed or returned by a tool.

The catalog client intentionally disables environment-proxy inheritance for
`catalog.ustc.edu.cn`: the site treats proxied traffic as off-campus while a
direct campus-network request is public. No CAS fallback is attempted for that
site.
