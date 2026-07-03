"""Proxy pool: sources, rotation strategies and health tracking."""
from __future__ import annotations

import random
import threading
import time
import urllib.request
from collections.abc import Iterable
from pathlib import Path

from .proxy import Proxy, ProxyState, parse_proxy

STRATEGIES = ("round_robin", "random", "sticky")


class NoHealthyProxies(RuntimeError):
    """Every proxy in the pool is currently banned."""


class ProxyPool:
    """Thread-safe rotating proxy pool with failure-based cooldowns.

    Rotation strategies:
        round_robin  cycle through healthy proxies in order (default)
        random       pick a healthy proxy at random
        sticky       keep returning the same proxy for a given ``key``
                     (e.g. a target domain) until it goes unhealthy

    Health model: a proxy that fails ``max_failures`` times in a row is
    benched for ``cooldown * 2**(streak-1)`` seconds (capped at
    ``max_cooldown``), then automatically returns to rotation. A success
    resets its failure counter.
    """

    def __init__(
        self,
        proxies: Iterable[Proxy | str] = (),
        *,
        strategy: str = "round_robin",
        max_failures: int = 2,
        cooldown: float = 60.0,
        max_cooldown: float = 3600.0,
        default_scheme: str = "http",
    ) -> None:
        if strategy not in STRATEGIES:
            raise ValueError(f"unknown strategy {strategy!r}, expected one of {STRATEGIES}")
        self.strategy = strategy
        self.max_failures = max_failures
        self.cooldown = cooldown
        self.max_cooldown = max_cooldown
        self.default_scheme = default_scheme
        self._lock = threading.Lock()
        self._states: dict[Proxy, ProxyState] = {}
        self._order: list[Proxy] = []
        self._rr_index = 0
        self._sticky: dict[str, Proxy] = {}
        self.extend(proxies)

    # ------------------------------------------------------------- sources
    @classmethod
    def from_file(cls, path: str | Path, **kwargs) -> "ProxyPool":
        """One proxy per line; blank lines and ``#`` comments are skipped."""
        lines = Path(path).read_text().splitlines()
        return cls([l for l in lines if l.strip() and not l.lstrip().startswith("#")], **kwargs)

    @classmethod
    def from_url(cls, url: str, *, timeout: float = 15.0, **kwargs) -> "ProxyPool":
        """Fetch a plain-text proxy list (one per line) from a URL.

        Handy for provider endpoints that export your current proxy list.
        """
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
        lines = [l for l in body.splitlines() if l.strip() and not l.lstrip().startswith("#")]
        return cls(lines, **kwargs)

    def extend(self, proxies: Iterable[Proxy | str]) -> None:
        with self._lock:
            for item in proxies:
                proxy = item if isinstance(item, Proxy) else parse_proxy(item, self.default_scheme)
                if proxy not in self._states:
                    self._states[proxy] = ProxyState(proxy)
                    self._order.append(proxy)

    # ------------------------------------------------------------ rotation
    def get(self, key: str | None = None) -> Proxy:
        """Return the next healthy proxy according to the pool strategy.

        ``key`` is only used by the ``sticky`` strategy (any hashable label:
        target domain, account id, worker name...).
        """
        with self._lock:
            healthy = self._healthy_locked()
            if not healthy:
                raise NoHealthyProxies(
                    f"all {len(self._order)} proxies are cooling down; "
                    "retry later or add more proxies"
                )
            if self.strategy == "sticky" and key is not None:
                current = self._sticky.get(key)
                if current is not None and current in healthy:
                    return current
                choice = random.choice(healthy)
                self._sticky[key] = choice
                return choice
            if self.strategy == "random":
                return random.choice(healthy)
            self._rr_index = (self._rr_index + 1) % len(healthy)
            return healthy[self._rr_index]

    # -------------------------------------------------------------- health
    def mark_ok(self, proxy: Proxy) -> None:
        with self._lock:
            state = self._states.get(proxy)
            if state is not None:
                state.successes += 1
                state.failures = 0
                state.banned_until = 0.0

    def mark_failed(self, proxy: Proxy) -> None:
        with self._lock:
            state = self._states.get(proxy)
            if state is None:
                return
            state.failures += 1
            if state.failures >= self.max_failures:
                streak = state.failures - self.max_failures
                delay = min(self.cooldown * (2**streak), self.max_cooldown)
                state.banned_until = time.monotonic() + delay
                for key, sticky_proxy in list(self._sticky.items()):
                    if sticky_proxy == proxy:
                        del self._sticky[key]

    def remove(self, proxy: Proxy) -> None:
        with self._lock:
            self._states.pop(proxy, None)
            if proxy in self._order:
                self._order.remove(proxy)
            for key, sticky_proxy in list(self._sticky.items()):
                if sticky_proxy == proxy:
                    del self._sticky[key]

    # --------------------------------------------------------------- stats
    def _healthy_locked(self) -> list[Proxy]:
        now = time.monotonic()
        return [p for p in self._order if self._states[p].banned_until <= now]

    @property
    def healthy_count(self) -> int:
        with self._lock:
            return len(self._healthy_locked())

    def __len__(self) -> int:
        return len(self._order)

    def stats(self) -> dict[str, dict]:
        """Snapshot of per-proxy health, keyed by ``host:port``."""
        now = time.monotonic()
        with self._lock:
            return {
                p.address: {
                    "successes": s.successes,
                    "failures": s.failures,
                    "banned_for": max(0.0, round(s.banned_until - now, 1)),
                }
                for p, s in self._states.items()
            }
