"""Use a unique ordering key while retaining SeminarRadar's pagination checks."""

from __future__ import annotations


def create_seminar_client(session):
    from seminar_radar.client import SeminarClient

    class StableSeminarClient(SeminarClient):
        async def _query(self, url, action, data):
            if action == "wxbgbgdz":
                # Several reports share BGSJ; date-only ordering can repeat page boundaries.
                data = {**data, "*order": "-BGBM"}
            return await super()._query(url, action, data)

    return StableSeminarClient(session)
