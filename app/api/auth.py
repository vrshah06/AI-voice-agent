"""Authentication and JWKS endpoints for eClinicalWorks integration."""
from typing import Any, Dict
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.jwks import key_manager

router = APIRouter(tags=["eCW Authentication & JWKS"])


@router.get(
    "/.well-known/jwks.json",
    summary="eCW JWKS Public Key Set",
    description=(
        "Standards-compliant JSON Web Key Set (JWKS) endpoint per RFC 7517. "
        "Exposes only public key parameters (kty, use, alg, kid, n, e) for signature verification "
        "by the eClinicalWorks FHIR Authorization Server. Uses RS384 algorithm."
    ),
    response_class=JSONResponse,
)
async def get_well_known_jwks() -> Dict[str, Any]:
    """Return the RFC 7517 JWK Set containing our public signing key."""
    return key_manager.get_jwks()


@router.get(
    "/api/auth/jwks.json",
    summary="eCW JWKS Public Key Set (Alias)",
    description="Alias endpoint for the public JWKS set.",
    response_class=JSONResponse,
)
async def get_api_jwks() -> Dict[str, Any]:
    """Alias for /.well-known/jwks.json."""
    return key_manager.get_jwks()


@router.get(
    "/api/auth/ecw-status",
    summary="eCW Integration & Auth Status",
    description="Returns public metadata and readiness status for the eClinicalWorks SMART on FHIR integration.",
)
async def get_ecw_auth_status(request: Request) -> Dict[str, Any]:
    """Safe status overview of the eCW backend configuration."""
    base_url = str(request.base_url).rstrip("/")
    jwk = key_manager.get_public_jwk()

    return {
        "status": "ready" if settings.ECW_CLIENT_ID else "pending_client_id",
        "ecw_enabled": settings.ECW_ENABLED,
        "environment": settings.ECW_ENV,
        "client_id_configured": bool(settings.ECW_CLIENT_ID),
        "client_id_preview": (
            f"{settings.ECW_CLIENT_ID[:6]}...{settings.ECW_CLIENT_ID[-4:]}"
            if len(settings.ECW_CLIENT_ID) > 10
            else (settings.ECW_CLIENT_ID or "NOT_CONFIGURED")
        ),
        "key_id": key_manager.key_id,
        "algorithm": "RS384",
        "public_jwks_url": f"{base_url}/.well-known/jwks.json",
        "token_url": settings.ECW_TOKEN_URL,
        "fhir_base_url_configured": bool(settings.ECW_FHIR_BASE_URL),
        "scopes": settings.ECW_SCOPES,
        "registration_type": "Backend App (Backend Services)",
        "oauth_grant_type": "client_credentials",
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
    }
