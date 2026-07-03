"""Playwright integration: per-context rotating proxies.

Playwright accepts a proxy per browser launch or per context. The natural
rotation unit is the context::

    from playwright.sync_api import sync_playwright
    from proxyspin import ProxyPool
    from proxyspin.playwright_helper import proxy_settings

    pool = ProxyPool.from_file("proxies.txt", strategy="sticky")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(proxy=proxy_settings(pool, key="job-42"))
        page = context.new_page()
        page.goto("https://example.com")

Async API is identical — ``proxy_settings`` is plain data, no I/O.
"""
from __future__ import annotations

from .pool import ProxyPool
from .proxy import Proxy


def proxy_settings(pool_or_proxy: ProxyPool | Proxy, key: str | None = None) -> dict:
    """Build the ``proxy`` dict Playwright expects, from a pool or a proxy.

    Credentials are passed via the dedicated fields (Playwright ignores
    userinfo embedded in the server URL).
    """
    proxy = pool_or_proxy.get(key=key) if isinstance(pool_or_proxy, ProxyPool) else pool_or_proxy
    settings: dict = {"server": f"{proxy.scheme}://{proxy.host}:{proxy.port}"}
    if proxy.username is not None:
        settings["username"] = proxy.username
    if proxy.password is not None:
        settings["password"] = proxy.password
    return settings
