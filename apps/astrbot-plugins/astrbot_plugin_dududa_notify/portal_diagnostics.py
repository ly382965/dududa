"""Bounded, value-free diagnostics for unexpected graduate-portal responses."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urljoin, urlsplit


class PortalResponseError(RuntimeError):
    pass


MARKERS = (
    "系统维护",
    "系统繁忙",
    "服务不可用",
    "登录失效",
    "请重新登录",
    "访问过于频繁",
    "访问被拒绝",
    "无访问权限",
    "session",
    "login",
    "captcha",
    "Bad Gateway",
    "Gateway Time-out",
    "Gateway Timeout",
    "Service Unavailable",
    "Internal Server Error",
    "Access Denied",
    "SQLException",
    "SQLNestedException",
    "NullPointerException",
    "OutOfMemoryError",
    "连接池",
    "数据库",
    "数据库连接",
    "系统错误",
    "发生错误",
    "系统异常",
    "Could not get JDBC Connection",
    "PoolDisabledSQLException",
    "ResourceDisabledException",
    "Pool gsapp_ds1 is suspended",
    "Socket read timed out",
)


def response_summary(response):
    text = response.text
    content_type = response.headers.get("content-type", "").split(";", 1)[0]
    upstream = response.headers.get("x-upstream-ip", "")
    result = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "path": response.url.path,
        "http_status": response.status_code,
        "content_type": content_type
        if content_type in {"text/html", "application/json", "text/plain"}
        else "other",
        "bytes": len(response.content),
        "upstream": upstream if re.fullmatch(r"[0-9.:]{1,45}", upstream) else "unknown",
        "has_page_meta": "pageMeta" in text,
        "has_identity_field": '"USERID"' in text,
        "markers": [
            marker for marker in MARKERS if marker.casefold() in text.casefold()
        ],
        "school_error_codes": sorted(set(re.findall(r"\bE\d{10}\b", text))),
    }
    try:
        payload = response.json()
    except ValueError:
        result["body_kind"] = (
            "html"
            if re.search(r"<(?:html|head|body)\b", text, re.IGNORECASE)
            else "non_json"
        )
    else:
        result["body_kind"] = "json"
        if isinstance(payload, dict):
            result["known_fields"] = [
                key
                for key in (
                    "code",
                    "success",
                    "msg",
                    "message",
                    "error",
                    "datas",
                    "models",
                )
                if key in payload
            ]
            code = payload.get("code")
            if isinstance(code, int) or (
                isinstance(code, str) and re.fullmatch(r"-?\d{1,10}", code)
            ):
                result["code"] = code
            if isinstance(payload.get("success"), bool):
                result["success"] = payload["success"]
            datas = payload.get("datas")
            result["has_homework_rows"] = (
                isinstance(datas, dict)
                and isinstance(datas.get("wdzycx"), dict)
                and isinstance(datas["wdzycx"].get("rows"), list)
            )
            result["has_seminar_rows"] = (
                isinstance(datas, dict)
                and isinstance(datas.get("wxbgbgdz"), dict)
                and isinstance(datas["wxbgbgdz"].get("rows"), list)
            )
    return result


async def observe_portal_response(response):
    directory = os.environ.get("DUDUDA_PORTAL_DIAGNOSTIC_DIR")
    path = response.url.path
    if response.url.host != "yjs1.ustc.edu.cn":
        return
    source = next(
        (
            name
            for key, name in (
                ("/wdzyappustc/", "homework"),
                ("/xsbgglappustc/", "seminar"),
                ("/yjsemaphome/", "portal"),
                ("/yjsrzfwapp/dbLogin/", "portal"),
            )
            if key in path
        ),
        None,
    )
    if source is None or not (
        path.endswith("/*default/index.do") or "/modules/" in path or source == "portal"
    ):
        return
    await response.aread()
    info = response_summary(response)
    database_failure = info["body_kind"] == "html" and (
        "Could not get JDBC Connection" in info["markers"]
        or "PoolDisabledSQLException" in info["markers"]
    )
    try:
        reason = "database_unavailable" if database_failure else None
        redirect = urlsplit(
            urljoin(str(response.url), response.headers.get("location", ""))
        )
        if (
            not reason
            and response.is_redirect
            and "/yjsrzfwapp/dbLogin/" in redirect.path
        ):
            reason = "redirected_to_graduate_login"
        elif not reason and response.is_redirect:
            return
        elif not reason and response.status_code != 200:
            reason = "unexpected_http_status"
        elif (
            not reason
            and path.endswith("/*default/index.do")
            and not info["has_page_meta"]
        ):
            reason = "application_page_without_identity"
        elif not reason and "/modules/" in path and info["body_kind"] != "json":
            reason = "api_returned_non_json"
        elif not reason and (
            info.get("success") is False or info.get("code", 0) not in (0, "0")
        ):
            reason = "api_business_error"
        elif (
            not reason
            and path.endswith("/wdzycx.do")
            and not info.get("has_homework_rows")
        ):
            reason = "homework_rows_missing"
        elif (
            not reason
            and path.endswith("/wxbgbgdz.do")
            and not info.get("has_seminar_rows")
        ):
            reason = "seminar_rows_missing"
        if reason is not None and directory:
            root = Path(directory)
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            log = root / f"{source}.jsonl"
            handler = RotatingFileHandler(
                log, maxBytes=131072, backupCount=1, encoding="utf-8"
            )
            try:
                log.chmod(0o600)
                handler.setFormatter(logging.Formatter("%(message)s"))
                handler.emit(
                    logging.LogRecord(
                        "portal",
                        logging.WARNING,
                        "",
                        0,
                        json.dumps({"reason": reason, **info}, ensure_ascii=False),
                        (),
                        None,
                    )
                )
            finally:
                handler.close()
    except Exception as exc:  # noqa: BLE001 - never log raw response content or credentials
        logging.getLogger(__name__).warning(
            "Portal diagnostic recording failed (%s)", type(exc).__name__
        )
    if database_failure:
        raise PortalResponseError("campus_database_unavailable")
