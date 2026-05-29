"""Authentication and security helpers."""
import hmac
import hashlib
from fastapi import Header, HTTPException, Request, status
from app.config.settings import settings


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Gate mutating endpoints behind a server-side API key.

    Returns 503 if the server has no key configured (fail closed) and 401 if the
    provided key does not match. Comparison is constant-time.
    """
    if not settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key not configured on server; mutating endpoints disabled.",
        )
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header.",
        )


async def verify_github_signature(request: Request) -> bytes:
    """Verify GitHub webhook HMAC-SHA256 signature.

    Fails closed: if no secret is configured the endpoint refuses all requests.
    Returns the raw request body so callers can re-parse without re-reading.
    """
    if not settings.github_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook secret not configured; webhook disabled.",
        )

    signature = request.headers.get("X-Hub-Signature-256", "")
    if not signature.startswith("sha256="):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed signature header.",
        )

    body = await request.body()
    expected = "sha256=" + hmac.new(
        settings.github_webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature.",
        )

    return body
