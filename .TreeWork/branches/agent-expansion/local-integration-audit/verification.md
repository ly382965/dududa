# Verification

Branch: local-integration-audit

## Latest Verification

- Command: fixed S19 dual-Python/Eval/proactive/fault/Web/package/Compose/secret/
  image/rollback matrix, aggregated by `ops/cli/audit_release_candidate.py`.
- Result: 18/18 required gates passed. Python 3.10.20 and 3.12.13 each passed
  651 repository tests with two identical skips; worker 2/2 on each; committed
  Eval 350 cases; proactive 3/3; fault sample 10/10; Web Unit/Server 108,
  Playwright 6/6, audit/typecheck/build passed; package/static 39, Compose 5 and
  secret scan 824 passed. AstrBot smoke ran 19 plugin/composition tests plus
  package/MCP checks; Web image loopback health passed under `--network none`.
- Result: previous source archive digest
  `sha256:d9cb4faf06cc0ad14a630256d7cff933389030f5ef7d26ee302869b77f987cd5`;
  rollback evidence covers successful restore/manual rollback and an unhealthy
  candidate with exactly one rollback. Inventory covers all 18 catalogued
  surfaces (10 remove candidates, 7 retain live, 1 blocked unknown).
- Coverage gap: real Provider/source/QQ latency and cost, human Chinese/Profile/
  interruption quality, production Trace retention and S23 authorization remain
  external. The pilot policy intentionally keeps `s23_ready=false`.
- Recorded: full logs and atomic 0600 receipts remain in the private S19
  evidence directory. The aggregate candidate receipt is generated only after
  this documentation commit is clean and is recorded by protected TreeWork
  verification rather than committed as a host artifact.
