"""requests integration: a Session that rotates proxies per request.

::

    from proxyspin import ProxyPool
    from proxyspin.requests_adapter import RotatingSession

    pool = ProxyPool.from_file("proxies.txt")
    session = RotatingSession(pool)
    r = session.get("https://httpbin.org/ip")   # each call uses the next proxy

Failures (connect errors, or responses with a status in ``ban_codes``)
mark the proxy in the pool and the call is retried through another proxy
up to ``max_retries`` times before the last error is raised.
"""
from __future__ import annotations

try:
    import requests
except ImportError as exc:  # pragma: no cover
    raise ImportError("proxyspin.requests_adapter needs requests: pip install proxyspin[requests]") from exc

from .pool import ProxyPool

DEFAULT_BAN_CODES = frozenset({403, 407, 429})


class RotatingSession(requests.Session):
    def __init__(
        self,
        pool: ProxyPool,
        *,
        max_retries: int = 3,
        ban_codes: frozenset[int] = DEFAULT_BAN_CODES,
    ) -> None:
        super().__init__()
        self.pool = pool
        self.max_retries = max_retries
        self.ban_codes = ban_codes

    def request(self, method, url, **kwargs):  # type: ignore[override]
        if "proxies" in kwargs:  # caller pinned a proxy — don't interfere
            return super().request(method, url, **kwargs)
        sticky_key = kwargs.pop("proxyspin_key", None)
        last_exc: Exception | None = None
        for _ in range(self.max_retries + 1):
            proxy = self.pool.get(key=sticky_key)
            kwargs["proxies"] = {"http": proxy.url, "https": proxy.url}
            try:
                response = super().request(method, url, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                self.pool.mark_failed(proxy)
                last_exc = exc
                continue
            if response.status_code in self.ban_codes:
                self.pool.mark_failed(proxy)
                last_response = response
                continue
            self.pool.mark_ok(proxy)
            return response
        if last_exc is not None:
            raise last_exc
        return last_response
