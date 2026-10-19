"""Graduate-portal login, including USTC's SSO gateway before ticket issuance."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from urllib.parse import parse_qs, parse_qsl, urljoin, urlsplit, urlunsplit

import httpx

if __package__:
    from .portal_diagnostics import PortalResponseError, observe_portal_response
else:
    from portal_diagnostics import PortalResponseError, observe_portal_response


class CampusAuthError(RuntimeError):
    pass


async def graduate_ticket(cas, service: str) -> str:
    client = cas._client
    url = str(
        client.build_request("GET", "/cas/login", params={"service": service}).url
    )
    expected = urlsplit(service)
    for _ in range(8):
        response = await client.get(url, follow_redirects=False)
        if not response.is_redirect or not response.headers.get("location"):
            raise CampusAuthError("cas_ticket_missing")
        location = urljoin(url, response.headers["location"])
        target = urlsplit(location)
        if target.username or target.password or target.fragment:
            raise CampusAuthError("cas_gateway_redirect_invalid")
        try:
            standard_port = target.port in (
                None,
                443 if target.scheme == "https" else 80,
            )
        except ValueError:
            standard_port = False
        if not standard_port:
            raise CampusAuthError("cas_gateway_redirect_invalid")
        query = parse_qs(target.query, keep_blank_values=True)
        gateway_redirect = target.scheme in {"http", "https"} and (
            target.hostname,
            target.path,
        ) in {
            ("id.ustc.edu.cn", "/cas/login"),
            ("id.ustc.edu.cn", "/.isg/gateway/sso-verify"),
            ("analytics.ustc.edu.cn", "/.isg/gateway/sso-init"),
            ("analytics.ustc.edu.cn", "/.isg/gateway/cas/callback"),
        }
        if "ticket" in query and not gateway_redirect:
            # Return the ticket without consuming it in the CAS client's cookie jar.
            if (
                target.scheme not in {"http", "https"}
                or target.hostname != expected.hostname
                or target.path != expected.path
                or [
                    (key, value)
                    for key, value in parse_qsl(target.query, keep_blank_values=True)
                    if key != "ticket"
                ]
                != parse_qsl(expected.query, keep_blank_values=True)
                or len(query["ticket"]) != 1
                or not query["ticket"][0]
                or any(char in query["ticket"][0] for char in "\r\n")
            ):
                raise CampusAuthError("cas_ticket_target_invalid")
            return query["ticket"][0]
        if not gateway_redirect:
            raise CampusAuthError("cas_gateway_redirect_invalid")
        # USTC advertises HTTP callbacks; keep gateway tickets on HTTPS too.
        url = urlunsplit(("https", target.hostname, target.path, target.query, ""))
    raise CampusAuthError("cas_gateway_redirect_limit")


@asynccontextmanager
async def graduate_session(credentials, timeout: float = 45):
    from pyustc.cas import CASClient
    from seminar_radar.auth import (
        PORTAL_ORIGIN,
        AuthError,
        _accept_ticket,
        resolve_service,
    )

    async with httpx.AsyncClient(
        base_url=PORTAL_ORIGIN,
        timeout=timeout,
        follow_redirects=False,
        event_hooks={"response": [observe_portal_response]},
    ) as client:
        try:
            async with asyncio.timeout(timeout):
                service = await resolve_service(client)
                async with AsyncExitStack() as stack:
                    cas = CASClient.login_by_pwd(
                        credentials.username, credentials.password
                    )
                    cas._client.timeout = httpx.Timeout(timeout)
                    stack.push_async_exit(cas)
                    await cas.__aenter__()
                    ticket = await graduate_ticket(cas, service)
                    await _accept_ticket(client, service, ticket)
        except PortalResponseError:
            raise CampusAuthError("campus_database_login_unavailable") from None
        except CampusAuthError:
            raise
        except (httpx.TimeoutException, TimeoutError):
            raise CampusAuthError("campus_connection_timeout") from None
        except httpx.HTTPError:
            raise CampusAuthError("campus_connection_failed") from None
        except AuthError:
            raise CampusAuthError("campus_portal_auth_failed") from None
        except Exception:  # noqa: BLE001 - never expose CAS tickets or raw login responses
            raise CampusAuthError("campus_login_failed") from None
        yield client
