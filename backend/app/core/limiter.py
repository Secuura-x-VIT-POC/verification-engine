from __future__ import annotations

try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address
except ImportError:  # pragma: no cover - optional until dependencies are installed
    class _NoopLimiter:
        def limit(self, *_args, **_kwargs):
            def decorator(func):
                return func

            return decorator

    limiter = _NoopLimiter()
    SLOWAPI_AVAILABLE = False
else:
    limiter = Limiter(key_func=get_remote_address)
    SLOWAPI_AVAILABLE = True
