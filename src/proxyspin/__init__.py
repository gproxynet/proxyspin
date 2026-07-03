"""proxyspin — rotating proxy pool for Scrapy, Playwright and requests."""

from .pool import NoHealthyProxies, ProxyPool
from .proxy import Proxy, parse_proxy

__version__ = "0.1.0"
__all__ = ["Proxy", "ProxyPool", "NoHealthyProxies", "parse_proxy", "__version__"]
