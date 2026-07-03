"""Scrapy downloader middleware with rotation, ban detection and retries.

Enable in ``settings.py``::

    DOWNLOADER_MIDDLEWARES = {
        "proxyspin.scrapy_middleware.ProxySpinMiddleware": 610,
    }

    PROXYSPIN_LIST = ["http://user:pass@gate.example.com:8000"]
    # or PROXYSPIN_FILE = "proxies.txt"
    # or PROXYSPIN_URL = "https://provider.example.com/api/list"

Optional settings (defaults shown)::

    PROXYSPIN_STRATEGY = "round_robin"      # round_robin | random | sticky
    PROXYSPIN_BAN_CODES = [403, 407, 429]   # responses treated as proxy bans
    PROXYSPIN_MAX_RETRIES = 3               # per-request proxy switches
    PROXYSPIN_MAX_FAILURES = 2              # pool: failures before cooldown
    PROXYSPIN_COOLDOWN = 60.0               # pool: base cooldown, seconds

Per-request control via ``request.meta``:

    ``proxy``               set explicitly to bypass the pool
    ``proxyspin_disabled``  truthy to skip proxying this request
    ``proxyspin_key``       sticky key (defaults to the request host)
"""
from __future__ import annotations

import logging

from .pool import NoHealthyProxies, ProxyPool
from .proxy import parse_proxy

logger = logging.getLogger(__name__)


class ProxySpinMiddleware:
    def __init__(self, pool: ProxyPool, ban_codes: frozenset[int], max_retries: int) -> None:
        self.pool = pool
        self.ban_codes = ban_codes
        self.max_retries = max_retries

    @classmethod
    def from_crawler(cls, crawler):
        settings = crawler.settings
        kwargs = {
            "strategy": settings.get("PROXYSPIN_STRATEGY", "round_robin"),
            "max_failures": settings.getint("PROXYSPIN_MAX_FAILURES", 2),
            "cooldown": settings.getfloat("PROXYSPIN_COOLDOWN", 60.0),
        }
        if settings.get("PROXYSPIN_URL"):
            pool = ProxyPool.from_url(settings.get("PROXYSPIN_URL"), **kwargs)
        elif settings.get("PROXYSPIN_FILE"):
            pool = ProxyPool.from_file(settings.get("PROXYSPIN_FILE"), **kwargs)
        else:
            proxies = settings.getlist("PROXYSPIN_LIST")
            if not proxies:
                from scrapy.exceptions import NotConfigured

                raise NotConfigured(
                    "set PROXYSPIN_LIST, PROXYSPIN_FILE or PROXYSPIN_URL"
                )
            pool = ProxyPool(proxies, **kwargs)
        logger.info("proxyspin: loaded %d proxies", len(pool))
        ban_codes = frozenset(
            int(c) for c in settings.getlist("PROXYSPIN_BAN_CODES", [403, 407, 429])
        )
        return cls(pool, ban_codes, settings.getint("PROXYSPIN_MAX_RETRIES", 3))

    # ----------------------------------------------------------- lifecycle
    def process_request(self, request, spider):
        if request.meta.get("proxyspin_disabled"):
            return None
        if "proxy" in request.meta and not request.meta.get("_proxyspin_managed"):
            return None  # user pinned a proxy explicitly — leave it alone
        key = request.meta.get("proxyspin_key") or _host(request.url)
        proxy = self.pool.get(key=key)
        request.meta["proxy"] = proxy.url
        request.meta["_proxyspin_managed"] = True
        return None

    def process_response(self, request, response, spider):
        proxy_url = request.meta.get("proxy")
        if not request.meta.get("_proxyspin_managed") or not proxy_url:
            return response
        if response.status in self.ban_codes:
            self.pool.mark_failed(parse_proxy(proxy_url))
            retried = self._retry(request, spider, reason=f"HTTP {response.status}")
            if retried is not None:
                return retried
        else:
            self.pool.mark_ok(parse_proxy(proxy_url))
        return response

    def process_exception(self, request, exception, spider):
        proxy_url = request.meta.get("proxy")
        if not request.meta.get("_proxyspin_managed") or not proxy_url:
            return None
        self.pool.mark_failed(parse_proxy(proxy_url))
        return self._retry(request, spider, reason=repr(exception))

    # ------------------------------------------------------------- helpers
    def _retry(self, request, spider, *, reason: str):
        retries = request.meta.get("_proxyspin_retries", 0)
        if retries >= self.max_retries:
            logger.warning(
                "proxyspin: giving up on %s after %d proxy switches (%s)",
                request.url, retries, reason,
            )
            return None
        try:
            proxy = self.pool.get(key=request.meta.get("proxyspin_key") or _host(request.url))
        except NoHealthyProxies:
            logger.warning("proxyspin: no healthy proxies left for %s", request.url)
            return None
        retry = request.copy()
        retry.meta["proxy"] = proxy.url
        retry.meta["_proxyspin_retries"] = retries + 1
        retry.dont_filter = True
        logger.debug("proxyspin: retrying %s via %s (%s)", request.url, proxy.address, reason)
        return retry


def _host(url: str) -> str:
    from urllib.parse import urlsplit

    return urlsplit(url).hostname or url
