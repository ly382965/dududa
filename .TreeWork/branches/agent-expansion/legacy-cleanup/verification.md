# Verification

Branch: legacy-cleanup

## Latest Verification

- Command: Python 3.12 complete `unittest discover -s tests -t .`; Python 3.10
  isolated S22 risk sample; root and worker MCP contracts; clean wheel install;
  root/canonical Compose comparison; no-network read-only AstrBot image smoke;
  import-boundary, secret, lock, Shell, compile, JSON and whitespace checks.
- Result: verified. Python 3.12 `651 OK / 2 host-only skips`; Python 3.10
  `32 OK / 2 host-only skips`; worker `2 OK`; root worker/Capability `11 OK`;
  image plugin tests `19 OK`; import/static `15 OK`; secret scan `824 files`.
  Image ID is `sha256:ca19efc3d7d6a1fc608f34ee80e057502b35143ed72619988ef9f6df1dbc5c0a`;
  Compose contract digest is `sha256:305745204859c1b50f120dcc697af0319df01e623e942b1e3ae03dd44ca5f0da`.
  Exact S19 archive is mode 0600, 10,506,240 bytes, commit `e303dc8`, SHA-256
  `80500b51187905a45801e195a3d906adac2b11fcbced172a0657e3f00386dc77`.
- Coverage gap: no Web/Eval/30-day rerun because S22 changes no such surface;
  S19 evidence remains authoritative. No real Provider/source/QQ, production
  container mutation, live send, human quality or online Bandit evidence.
- Recorded: 2026-08-10 Asia/Shanghai.
