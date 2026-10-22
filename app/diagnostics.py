"""Read-only HTTPS probe with DNS/IP restrictions and no redirects/proxies."""
import asyncio
import ipaddress
import os
import socket
import ssl
import time
from urllib.parse import urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver


class TargetRejected(ValueError):
    pass


class PublicResolver(AbstractResolver):
    """Resolve once per connection and return only public addresses to the connector."""
    async def resolve(self, host, port=0, family=socket.AF_INET):
        loop = asyncio.get_running_loop()
        records = await loop.getaddrinfo(host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
        results = []
        for fam, _, _, _, address in records:
            ip = ipaddress.ip_address(address[0])
            if not ip.is_global:
                continue
            results.append({"hostname": host, "host": str(ip), "port": port,
                            "family": fam, "proto": socket.IPPROTO_TCP, "flags": 0})
        if not results:
            raise TargetRejected('DNS returned no permitted public IP addresses')
        return results

    async def close(self):
        pass


def check_target(url: str) -> str:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or '').lower().rstrip('.')
    allowed = {h.strip().lower().rstrip('.') for h in os.getenv('ALLOWED_HTTPS_HOSTS', 'example.com').split(',') if h.strip()}
    if parsed.scheme != 'https' or not hostname or parsed.username or parsed.password or parsed.fragment:
        raise TargetRejected('Only HTTPS URLs without credentials or fragments are permitted')
    try:
        port = parsed.port
    except ValueError as exc:
        raise TargetRejected('Invalid port') from exc
    if port not in (None, 443):
        raise TargetRejected('Only HTTPS port 443 is permitted')
    if hostname not in allowed:
        raise TargetRejected('Host is not on ALLOWED_HTTPS_HOSTS')
    try:
        ipaddress.ip_address(hostname)
        raise TargetRejected('IP literal targets are not permitted')
    except ValueError as exc:
        if isinstance(exc, TargetRejected):
            raise
    return hostname


async def probe_https(url: str) -> dict:
    check_target(url)
    timeout_seconds = min(max(float(os.getenv('PROBE_TIMEOUT_SECONDS', '5')), 1), 15)
    start = time.perf_counter()
    result = {"http_status": None, "latency_ms": None, "classification": None,
              "error_type": None, "error_message": None, "remote_ip": None}
    timeout = aiohttp.ClientTimeout(total=timeout_seconds, connect=timeout_seconds)
    connector = aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False,
                                     ssl=ssl.create_default_context(), limit=1)
    try:
        async with aiohttp.ClientSession(connector=connector, timeout=timeout,
                                         trust_env=False, auto_decompress=False) as session:
            async with session.get(url, allow_redirects=False, headers={'Accept': '*/*'},
                                   max_line_size=8190, max_field_size=8190) as response:
                result['http_status'] = response.status
                transport = response.connection.transport if response.connection else None
                peer = transport.get_extra_info('peername') if transport else None
                result['remote_ip'] = peer[0] if peer else None
                if 200 <= response.status < 300:
                    result['classification'] = 'healthy'
                elif 300 <= response.status < 400:
                    result['classification'] = 'redirect_not_followed'
                elif 400 <= response.status < 500:
                    result['classification'] = 'http_4xx'
                elif 500 <= response.status < 600:
                    result['classification'] = 'http_5xx'
                else:
                    result['classification'] = 'other_http'
    except (asyncio.TimeoutError, TimeoutError):
        result.update(classification='timeout', error_type='timeout', error_message='HTTPS request timed out')
    except (aiohttp.ClientConnectorCertificateError, aiohttp.ClientSSLError) as exc:
        result.update(classification='tls_error', error_type=type(exc).__name__, error_message='TLS certificate/handshake failed')
    except (aiohttp.ClientError, OSError, TargetRejected) as exc:
        result.update(classification='network_error', error_type=type(exc).__name__, error_message='HTTPS connection failed or destination rejected')
    finally:
        result['latency_ms'] = round((time.perf_counter() - start) * 1000, 2)
    return result
