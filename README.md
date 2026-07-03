# proxyspin

Rotating proxy pool for **Scrapy**, **Playwright** and **requests** — with health tracking, ban detection, sticky sessions and a built-in list checker. Zero required dependencies, pure stdlib.

```
pip install proxyspin
```

Why another one? The classic `scrapy-rotating-proxies` hasn't been updated in years and is Scrapy-only. `proxyspin` is one small pool you can share across Scrapy spiders, Playwright contexts and plain `requests` code, with the same health model everywhere.

## Features

- **One pool, three integrations** — Scrapy middleware, Playwright helper, `requests` session.
- **Rotation strategies** — `round_robin`, `random`, `sticky` (same proxy per domain/account/worker until it dies).
- **Health model** — a proxy failing N times in a row is benched with exponential backoff and returns automatically; a success resets its streak.
- **Ban detection** — configurable HTTP codes (403/407/429 by default) count as proxy failures and trigger a retry through the next proxy.
- **Any list format** — `scheme://user:pass@host:port`, `host:port`, `host:port:user:pass`, `user:pass@host:port`; load from a list, a file or a provider URL.
- **CLI checker** — `proxyspin check proxies.txt` tests the whole list concurrently and can write the alive ones out.

## Quickstart

### The pool

```python
from proxyspin import ProxyPool

pool = ProxyPool.from_file("proxies.txt", strategy="round_robin")
# or inline:
pool = ProxyPool(["http://user:pass@gate1.example.com:8000", "10.0.0.2:8000"])
# or straight from your provider's export endpoint:
pool = ProxyPool.from_url("https://provider.example.com/api/my-list.txt")

proxy = pool.get()          # -> Proxy; proxy.url is ready to use
pool.mark_failed(proxy)     # bench it after repeated failures
pool.mark_ok(proxy)         # reset its failure streak
```

### Scrapy

```python
# settings.py
DOWNLOADER_MIDDLEWARES = {
    "proxyspin.scrapy_middleware.ProxySpinMiddleware": 610,
}
PROXYSPIN_FILE = "proxies.txt"
PROXYSPIN_STRATEGY = "sticky"          # one proxy per target host
PROXYSPIN_BAN_CODES = [403, 429]       # these responses rotate the proxy
PROXYSPIN_MAX_RETRIES = 3
```

Per-request overrides: set `request.meta["proxy"]` to pin a proxy, `meta["proxyspin_disabled"] = True` to skip proxying, `meta["proxyspin_key"]` to control stickiness.

### Playwright

```python
from playwright.sync_api import sync_playwright
from proxyspin import ProxyPool
from proxyspin.playwright_helper import proxy_settings

pool = ProxyPool.from_file("proxies.txt", strategy="sticky")

with sync_playwright() as p:
    browser = p.chromium.launch()
    for account in accounts:
        context = browser.new_context(proxy=proxy_settings(pool, key=account.id))
        # each account keeps its own IP for the whole session
```

### requests

```python
from proxyspin import ProxyPool
from proxyspin.requests_adapter import RotatingSession

session = RotatingSession(ProxyPool.from_file("proxies.txt"))
print(session.get("https://httpbin.org/ip").json())   # new IP per call
```

### Check a list

```
$ proxyspin check proxies.txt --workers 100 --alive-out alive.txt
OK   45.155.10.4:8000        612 ms  HTTP 200
DEAD 91.10.77.2:3128                 TimeoutError
...
118/200 alive
wrote 118 proxies to alive.txt
```

## Providers

`proxyspin` works with any proxy source: your own servers, free lists, or commercial providers. Example with [GProxy](https://gproxy.net/?utm_source=github&utm_medium=readme&utm_campaign=proxyspin) residential/mobile gateways (rotation happens server-side, so a pool of one entry per gateway is enough — use `sticky` if you need session pinning):

```python
pool = ProxyPool([
    "http://USER:PASS@gate.gproxy.net:8000",   # residential, rotating
])
```

Any other provider works the same way — put its gateway or IP list into the pool.

## Health model in one paragraph

Every proxy starts healthy. `mark_failed` increments its failure streak; when the streak reaches `max_failures` (default 2) the proxy is benched for `cooldown * 2**overshoot` seconds (default base 60 s, capped at 1 h), then automatically rejoins rotation. `mark_ok` resets the streak. The Scrapy middleware and `RotatingSession` call these for you based on exceptions and ban codes; with Playwright you call them yourself since only your code knows what a "ban" looks like for your flow.

## License

MIT
