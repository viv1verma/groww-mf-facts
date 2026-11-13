"""HTTPS helper shared by the AMFI and LLM clients.

Some Python installs (notably the python.org build on macOS) ship without
root certificates, so HTTPS fails with CERTIFICATE_VERIFY_FAILED. If the
`certifi` package is installed we use its certificate bundle. Certificate
verification is never turned off.
"""
import ssl
import urllib.request
from functools import lru_cache


@lru_cache(maxsize=1)
def ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def urlopen(request, timeout: float):
    return urllib.request.urlopen(request, timeout=timeout, context=ssl_context())
