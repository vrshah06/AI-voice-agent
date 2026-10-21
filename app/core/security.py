"""Security utilities for API key and webhook authentication."""
from typing import Optional
from fastapi import Header, HTTPException, status
from app.core.config import settings


async def verify_retell_or_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-Api-Key"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> bool:
    """Validate incoming webhook / tool request authentication.

    If RETELL_API_KEY or WEBHOOK_SECRET_KEY is configured in settings,
    the request must supply a matching key via X-Api-Key header or
    Authorization: Bearer <key>.
    If no key is configured in the environment (e.g., local development),
    requests are permitted with a log warning.
    """
    configured_secrets = [k for k in [settings.RETELL_API_KEY, settings.WEBHOOK_SECRET_KEY] if k]

    # If no secrets are configured in settings, allow (dev mode)
    if not configured_secrets:
        return True

    # Check X-Api-Key header
    if x_api_key and x_api_key in configured_secrets:
        return True

    # Check Authorization: Bearer <token>
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
            if token in configured_secrets:
                return True
        elif authorization in configured_secrets:
            return True

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized: Invalid or missing API key. Provide valid X-Api-Key or Authorization header.",
        headers={"WWW-Authenticate": "Bearer"},
    )
