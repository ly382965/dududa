# ustc-notice-mcp

MCP server exposing public notices published by the USTC Office of Academic
Affairs (`https://www.teach.ustc.edu.cn/notice`).

## Data

Only public pages are fetched, with a per-request delay (default 1.0s) and the
site's `robots.txt` honoured. No login, no credentials.

## Tools

- `notice_stats` — cache statistics.
- `list_notices(limit, refresh)` — recent notices from the cache.
- `get_notice(notice_id, refresh)` — full text + attachments of one notice.
- `search_notices(query, limit, refresh)` — keyword search over cached titles/bodies.
- `refresh_notice(notice_id)` — re-fetch one notice detail.
- `check_robots` — fetch/cache `robots.txt` for audit.

## CLI

```bash
python run_ustc_notice_mcp.py --db-path data/ustc-notice.sqlite3   # MCP server
ustc-notice-mcp-cli --db-path data/ustc-notice.sqlite3 listing --refresh
ustc-notice-mcp-cli --db-path data/ustc-notice.sqlite3 get 20484
ustc-notice-mcp-cli --db-path data/ustc-notice.sqlite3 search 选课
```

## Deploy

Installed into the AstrBot image via `docker/astrbot/Dockerfile`, mounted
read-only at `/AstrBot/data/ustc-notice-mcp`, and registered in
`config/astrbot/mcp_server.json` (synced by `scripts/sync_runtime.py`).