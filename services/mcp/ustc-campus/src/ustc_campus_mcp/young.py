from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from .common import fetched_at


class YoungClient:
    def __init__(self, username: str | None = None, password: str | None = None) -> None:
        self.username = username if username is not None else os.getenv("USTC_CAS_USR", "")
        self.password = password if password is not None else os.getenv("USTC_CAS_PWD", "")

    def status(self) -> dict[str, Any]:
        configured = bool(self.username and self.password)
        return {
            "ok": True,
            "available": configured,
            "authentication": "configured" if configured else "missing_secret",
            "reason": None if configured else "USTC CAS SecretRefs are not configured",
            "provider": "pyustc",
            "provider_revision": "f16d9465fd572463cb1b239d310e02010593386c",
            "fetched_at": fetched_at(),
        }

    async def search_activities(
        self,
        query: str = "",
        state: str = "applying",
        module_id: str = "",
        department_id: str = "",
        label_ids: list[str] | None = None,
        start_time: str = "",
        end_time: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        unavailable = self._unavailable()
        if unavailable:
            return unavailable
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        from pyustc.young import (
            Department,
            Label,
            Module,
            SCFilter,
            SecondClass,
            TimePeriod,
        )

        period = None
        if start_time:
            period = TimePeriod(self._date_time(start_time), self._date_time(end_time or start_time))
        filter_value = SCFilter(
            name=query or None,
            time_period=period,
            module=Module(module_id, module_id) if module_id else None,
            department=Department(department_id, department_id, level=-1) if department_id else None,
            labels=[Label(value, value) for value in (label_ids or [])],
        )
        apply_ended = state.casefold() in {"ended", "finished", "history"}
        try:
            async with self._service():
                values = [
                    self._public_activity(item)
                    async for item in SecondClass.find(
                        filter_value,
                        apply_ended=apply_ended,
                        expand_series=False,
                        max=limit,
                        size=min(limit, 50),
                    )
                ]
        except RuntimeError:
            return self._upstream_unavailable()
        return self._result(values)

    async def get_activity(self, activity_id: str, include_children: bool = False) -> dict[str, Any]:
        unavailable = self._unavailable()
        if unavailable:
            return unavailable
        from pyustc.young import SecondClass

        try:
            async with self._service():
                activity = SecondClass(activity_id, data={})
                await activity.update()
                item = self._public_activity(activity)
                children = (
                    [
                        self._public_activity(value)
                        for value in await activity.get_children()
                    ]
                    if include_children
                    else []
                )
        except RuntimeError:
            return self._upstream_unavailable(
                extra={"activity": None, "children": []}
            )
        return self._result([item], extra={"activity": item, "children": children})

    async def list_facets(self, facet: str) -> dict[str, Any]:
        unavailable = self._unavailable()
        if unavailable:
            return unavailable
        from pyustc.young import Department, Label, Module

        kind = facet.casefold()
        if kind not in {"module", "label", "department"}:
            raise ValueError("facet must be module, department or label")
        try:
            async with self._service():
                if kind == "module":
                    items = [
                        {"id": value.value, "name": value.text}
                        for value in await Module.get_available_tags()
                    ]
                elif kind == "label":
                    items = [
                        {"id": value.id, "name": value.name}
                        for value in await Label.get_available_tags()
                    ]
                else:
                    root = await Department.get_root_dept()
                    items = []

                    def visit(value: Any) -> None:
                        items.append(
                            {"id": value.id, "name": value.name, "level": value.level}
                        )
                        for child in value.children:
                            visit(child)

                    # The raw tree includes thousands of class and club nodes.
                    # The public filter lists university/school/department entries.
                    visit(root)
                    items = [item for item in items if item["level"] <= 1]
        except RuntimeError:
            return self._upstream_unavailable()
        return self._result(items[:100], extra={"total": len(items)})

    @asynccontextmanager
    async def _service(self) -> AsyncIterator[None]:
        from pyustc.cas import CASClient
        from pyustc.young import YouthService

        try:
            async with (
                CASClient.login_by_pwd(self.username, self.password) as cas,
                YouthService(retry=1) as service,
            ):
                await service.login(cas)
                yield
        except Exception as exc:
            raise RuntimeError("young_authentication_or_upstream_failed") from exc

    def _unavailable(self) -> dict[str, Any] | None:
        if self.username and self.password:
            return None
        return {
            "ok": False,
            "available": False,
            "error": "cas_credentials_missing",
            "authentication": "missing_secret",
            "items": [],
            "total": 0,
            "source_url": "https://young.ustc.edu.cn/",
            "fetched_at": fetched_at(),
        }

    @staticmethod
    def _upstream_unavailable(
        *, extra: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "available": False,
            "error": "young_authentication_or_upstream_failed",
            "authentication": "failed",
            "items": [],
            "total": 0,
            "source_url": "https://young.ustc.edu.cn/",
            "fetched_at": fetched_at(),
            **(extra or {}),
        }

    @staticmethod
    def _date_time(value: str) -> datetime:
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("time must use ISO-8601") from exc

    @staticmethod
    def _activity(value: Any) -> dict[str, Any]:
        raw = dict(value.data)
        status_code = raw.get("itemStatus")
        status_text = f"unknown:{status_code}"
        try:
            status_text = value.status.text
        except (KeyError, ValueError):
            pass
        labels = []
        raw_ids = str(raw.get("itemLable") or "").split(",")
        raw_names = raw.get("lableNames") or []
        if isinstance(raw_names, str):
            raw_names = [item for item in raw_names.split(",") if item]
        for index, name in enumerate(raw_names if isinstance(raw_names, list) else []):
            labels.append({"id": raw_ids[index] if index < len(raw_ids) else None, "name": name})
        registered = raw.get("applyNum")
        capacity_limit = raw.get("peopleNum")
        is_registered = raw.get("booleanRegistration") == 1
        return {
            "activity_id": value.id,
            "name": raw.get("itemName"),
            "status": {"code": status_code, "text": status_text},
            "kind": "series" if raw.get("itemCategory") == "1" else "activity",
            "apply_window": {"start": raw.get("applySt"), "end": raw.get("applyEt")},
            "event_window": {"start": raw.get("st"), "end": raw.get("et")},
            "valid_hours": raw.get("validHour"),
            "capacity": {"registered": registered, "limit": capacity_limit},
            "is_registered": is_registered,
            "can_apply": (
                status_code == 26
                and not is_registered
                and isinstance(registered, int)
                and isinstance(capacity_limit, int)
                and registered < capacity_limit
            ),
            "module": {"id": raw.get("module"), "name": raw.get("moduleName")},
            "department": {"id": raw.get("businessDeptId"), "name": raw.get("bussinessDeptName")},
            "labels": labels,
            "description": raw.get("conceive"),
            "contact": raw.get("tel"),
        }

    @classmethod
    def _public_activity(cls, value: Any) -> dict[str, Any]:
        item = cls._activity(value)
        for account_field in ("is_registered", "can_apply", "contact"):
            item.pop(account_field, None)
        return item

    @staticmethod
    def _result(items: list[dict[str, Any]], extra: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "ok": True,
            "available": True,
            "authentication": "connected",
            "items": items,
            "total": len(items),
            "source_url": "https://young.ustc.edu.cn/",
            "fetched_at": fetched_at(),
            **(extra or {}),
        }
