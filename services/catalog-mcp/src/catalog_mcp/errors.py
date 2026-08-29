from __future__ import annotations


class CatalogError(Exception):
    """Base error for the catalog MCP."""


class RateLimitedError(CatalogError):
    pass
