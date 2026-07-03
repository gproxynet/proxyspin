"""Proxy model and parsing of common list formats."""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urlsplit

SUPPORTED_SCHEMES = ("http", "https", "socks4", "socks5", "socks5h")


@dataclass(frozen=True)
class Proxy:
    host: str
    port: int
    scheme: str = "http"
    username: str | None = None
    password: str | None = None

    @property
    def url(self) -> str:
        """Full proxy URL, credentials included if present."""
        auth = ""
        if self.username is not None:
            auth = quote(self.username, safe="")
            if self.password is not None:
                auth += ":" + quote(self.password, safe="")
            auth += "@"
        return f"{self.scheme}://{auth}{self.host}:{self.port}"

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.url


def parse_proxy(line: str, default_scheme: str = "http") -> Proxy:
    """Parse one proxy from any of the common formats.

    Accepted:
        scheme://user:pass@host:port
        scheme://host:port
        user:pass@host:port
        host:port
        host:port:user:pass
    """
    line = line.strip()
    if not line:
        raise ValueError("empty proxy line")

    if "://" in line:
        parts = urlsplit(line)
        if parts.scheme not in SUPPORTED_SCHEMES:
            raise ValueError(f"unsupported proxy scheme: {parts.scheme!r}")
        if not parts.hostname or not parts.port:
            raise ValueError(f"proxy needs host and port: {line!r}")
        return Proxy(
            host=parts.hostname,
            port=parts.port,
            scheme=parts.scheme,
            username=unquote(parts.username) if parts.username else None,
            password=unquote(parts.password) if parts.password else None,
        )

    if "@" in line:
        creds, _, hostport = line.rpartition("@")
        user, _, pwd = creds.partition(":")
        host, _, port = hostport.rpartition(":")
        _validate(host, port, line)
        return Proxy(host, int(port), default_scheme, user, pwd or None)

    pieces = line.split(":")
    if len(pieces) == 2:
        host, port = pieces
        _validate(host, port, line)
        return Proxy(host, int(port), default_scheme)
    if len(pieces) == 4:
        host, port, user, pwd = pieces
        _validate(host, port, line)
        return Proxy(host, int(port), default_scheme, user, pwd)
    raise ValueError(f"cannot parse proxy: {line!r}")


def _validate(host: str, port: str, line: str) -> None:
    if not host or not port.isdigit() or not 0 < int(port) < 65536:
        raise ValueError(f"cannot parse proxy: {line!r}")


@dataclass
class ProxyState:
    """Mutable health bookkeeping attached to a proxy inside a pool."""

    proxy: Proxy
    failures: int = 0
    successes: int = 0
    banned_until: float = 0.0
    extra: dict = field(default_factory=dict)
