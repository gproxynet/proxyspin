"""``proxyspin check`` — fast concurrent liveness check for a proxy list.

Zero dependencies: stdlib only (http/https proxies; socks lines are skipped).

::

    proxyspin check proxies.txt
    proxyspin check proxies.txt --url https://example.com --timeout 5 --workers 100
    proxyspin check proxies.txt --alive-out alive.txt
"""
from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .proxy import Proxy, parse_proxy

DEFAULT_TEST_URL = "http://httpbin.org/ip"


def check_one(proxy: Proxy, url: str, timeout: float) -> tuple[Proxy, float | None, str]:
    """Return (proxy, latency_seconds_or_None, detail)."""
    handler = urllib.request.ProxyHandler({"http": proxy.url, "https": proxy.url})
    opener = urllib.request.build_opener(handler)
    opener.addheaders = [("User-Agent", "proxyspin-check")]
    start = time.monotonic()
    try:
        with opener.open(url, timeout=timeout) as resp:
            resp.read(256)
            return proxy, time.monotonic() - start, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return proxy, None, f"HTTP {exc.code}"
    except Exception as exc:
        return proxy, None, exc.__class__.__name__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="proxyspin", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="check which proxies in a list are alive")
    check.add_argument("file", help="proxy list, one per line (any common format)")
    check.add_argument("--url", default=DEFAULT_TEST_URL, help="URL fetched through each proxy")
    check.add_argument("--timeout", type=float, default=10.0)
    check.add_argument("--workers", type=int, default=50)
    check.add_argument("--alive-out", help="write working proxies to this file")
    args = parser.parse_args(argv)

    proxies: list[Proxy] = []
    for line in Path(args.file).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            proxy = parse_proxy(line)
        except ValueError as exc:
            print(f"  skip: {exc}", file=sys.stderr)
            continue
        if proxy.scheme.startswith("socks"):
            print(f"  skip (socks not supported by checker): {proxy.address}", file=sys.stderr)
            continue
        proxies.append(proxy)

    if not proxies:
        print("no proxies to check", file=sys.stderr)
        return 2

    alive: list[tuple[Proxy, float]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(check_one, p, args.url, args.timeout) for p in proxies]
        for future in as_completed(futures):
            proxy, latency, detail = future.result()
            if latency is not None:
                alive.append((proxy, latency))
                print(f"OK   {proxy.address:<21} {latency * 1000:6.0f} ms  {detail}")
            else:
                print(f"DEAD {proxy.address:<21}          {detail}")

    print(f"\n{len(alive)}/{len(proxies)} alive")
    if args.alive_out:
        alive.sort(key=lambda item: item[1])
        Path(args.alive_out).write_text(
            "\n".join(proxy.url for proxy, _ in alive) + ("\n" if alive else "")
        )
        print(f"wrote {len(alive)} proxies to {args.alive_out}")
    return 0 if alive else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
