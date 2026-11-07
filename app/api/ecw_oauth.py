"""eClinicalWorks (eCW) Patient App OAuth 2.0 Authorization Flow & Callback Router.

Implements standards-compliant SMART on FHIR OAuth 2.0 Authorization Code Grant with PKCE (RFC 7636):
1. GET /api/ecw/patient/authorize: Initiates authorization with PKCE (S256) and anti-CSRF state.
   - Also provides GET /api/ecw/authorize as alias.
2. GET /api/ecw/callback: Handles exact registered redirect URI, validates state (anti-replay),
   and exchanges code for tokens using confidential/public client settings.
3. GET /api/ecw/patient/token-status (and /api/ecw/token-status): Safe diagnostics without secrets.
4. POST /api/ecw/patient/refresh: Refreshes access token using stored refresh token.
5. POST /api/ecw/patient/clear-token: Clears stored Patient App tokens from backend memory.

Security:
- Never logs or exposes PHI, authorization codes, access tokens, refresh tokens, or client secrets.
- Enforces single-use state validation to protect against CSRF and replay attacks.
- Keeps Provider App Backend Services authentication completely isolated.
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.core.config import settings
from app.services.ecw_client import ecw_client
from app.services.ecw_patient_auth import ecw_patient_auth_service
from app.services.ecw_token_store import (
    ecw_patient_state_store,
    ecw_patient_token_store,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ecw", tags=["eCW Patient App OAuth 2.0"])


@router.get(
    "/patient/authorize",
    summary="Initiate eCW Patient App OAuth 2.0 Authorization",
    description=(
        "Generates a cryptographically random anti-CSRF state and RFC 7636 PKCE pair (S256), "
        "then constructs the official eClinicalWorks SMART on FHIR Patient App authorization URL.\n\n"
        "- When `redirect=true` (default): Issues an HTTP 307 temporary redirect to the eCW login screen.\n"
        "- When `redirect=false`: Returns the authorization URL, state, and PKCE parameters in JSON format."
    ),
    responses={
        307: {"description": "Temporary redirect to eClinicalWorks OAuth authorization page."},
        200: {"description": "Returns authorization URL and state parameter as JSON."},
        400: {"description": "Client ID or authorize endpoint is not configured."},
    },
)
async def initiate_patient_authorization(
    redirect: bool = Query(
        True,
        description="Redirect browser to eCW authorization page (307) or return JSON payload.",
    ),
    scope: Optional[str] = Query(
        None,
        description="OAuth scopes override (defaults to configured ECW_PATIENT_SCOPES).",
    ),
    practice_code: Optional[str] = Query(
        None,
        description="Practice code override (defaults to configured ECW_PATIENT_PRACTICE_CODE).",
    ),
) -> Any:
    """Start Patient App OAuth 2.0 authorization code flow with PKCE."""
    result = ecw_patient_auth_service.initiate_authorization(
        scope=scope,
        practice_code=practice_code,
    )

    if redirect:
        return RedirectResponse(
            url=result["authorization_url"],
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )

    return result


@router.get(
    "/authorize",
    summary="Initiate eCW Authorization (Alias)",
    description="Alias for /api/ecw/patient/authorize.",
    include_in_schema=False,
)
async def initiate_authorization_alias(
    redirect: bool = Query(True),
    scope: Optional[str] = Query(None),
    practice_code: Optional[str] = Query(None),
) -> Any:
    """Alias for /api/ecw/patient/authorize."""
    return await initiate_patient_authorization(
        redirect=redirect,
        scope=scope,
        practice_code=practice_code,
    )


@router.get(
    "/callback",
    summary="eCW Patient App OAuth 2.0 Authorization Callback",
    description=(
        "Receives authorization code and state from eClinicalWorks at the exact registered redirect URI.\n\n"
        "1. Validates anti-forgery `state` and enforces single-use replay protection.\n"
        "2. Exchanges `code` and PKCE `code_verifier` (plus client secret if configured) for tokens.\n"
        "3. Stores tokens securely in backend memory (never exposed in response or logs).\n"
        "4. Returns safe status confirmation or browser success page."
    ),
    responses={
        200: {"description": "Authorization successful and tokens stored securely."},
        400: {"description": "Invalid/expired state, OAuth error, or code exchange rejection."},
        502: {"description": "Upstream error communicating with eCW OAuth server."},
    },
)
async def handle_ecw_callback(
    request: Request,
    code: Optional[str] = Query(None, description="OAuth authorization code issued by eCW"),
    state: Optional[str] = Query(None, description="Anti-CSRF state parameter"),
    error: Optional[str] = Query(None, description="Error code if authorization was denied"),
    error_description: Optional[str] = Query(None, description="Error description from eCW"),
) -> Any:
    """Handle OAuth callback redirect from eClinicalWorks authorization server."""
    accept_header = request.headers.get("accept", "").lower()
    is_browser = "text/html" in accept_header

    # 1. Check for OAuth error returned by eCW
    if error:
        logger.warning(
            "eCW OAuth callback returned error: %s (description: %s)",
            error,
            error_description,
        )
        if is_browser:
            return HTMLResponse(
                content=_render_html_status(
                    title="eClinicalWorks Authorization Failed",
                    is_success=False,
                    message=f"Authorization Error: {error}",
                    detail=error_description or "The user or practice declined authorization.",
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth authorization rejected: {error}. {error_description or ''}".strip(),
        )

    # 2. Validate and consume state (single-use / anti-replay)
    if not state or not state.strip():
        logger.warning("eCW OAuth callback missing state parameter")
        if is_browser:
            return HTMLResponse(
                content=_render_html_status(
                    title="Invalid Authorization Request",
                    is_success=False,
                    message="Missing OAuth state parameter.",
                    detail="Please start authorization from the clinic dashboard.",
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required 'state' query parameter in callback.",
        )

    stored_state = ecw_patient_state_store.validate_and_consume(state)
    if not stored_state:
        logger.warning("eCW OAuth callback state rejected: invalid, expired, or already consumed")
        if is_browser:
            return HTMLResponse(
                content=_render_html_status(
                    title="Authorization Session Expired",
                    is_success=False,
                    message="Invalid, expired, or already used OAuth state parameter.",
                    detail="Please initiate the authorization process again.",
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid, missing, or expired OAuth state parameter. Please restart authorization.",
        )

    # 3. Validate presence of authorization code
    if not code or not code.strip():
        logger.warning("eCW OAuth callback missing authorization code")
        if is_browser:
            return HTMLResponse(
                content=_render_html_status(
                    title="Authorization Code Missing",
                    is_success=False,
                    message="Authorization code was not provided in the callback request.",
                    detail="eClinicalWorks did not return a valid authorization code.",
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing 'code' query parameter in callback request.",
        )

    # 4. Exchange authorization code for tokens
    redirect_uri = stored_state.get("redirect_uri") or settings.ECW_PATIENT_REDIRECT_URI
    code_verifier = stored_state.get("code_verifier")

    try:
        safe_status = await ecw_patient_auth_service.exchange_authorization_code(
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
        )
    except HTTPException as exc:
        logger.error("Patient App token exchange failed: status=%d, detail=%s", exc.status_code, exc.detail)
        if is_browser:
            return HTMLResponse(
                content=_render_html_status(
                    title="Token Exchange Failed",
                    is_success=False,
                    message="Failed to exchange authorization code for access token.",
                    detail=str(exc.detail),
                ),
                status_code=exc.status_code,
            )
        raise

    # 5. Return success (clean confirmation, strictly no raw tokens or secrets)
    logger.info("eCW Patient App OAuth callback flow successfully completed.")

    if is_browser:
        return HTMLResponse(
            content=_render_html_status(
                title="Authorization Successful",
                is_success=True,
                message="eClinicalWorks Patient App OAuth 2.0 authorization completed successfully!",
                detail=(
                    f"AI Receptionist backend is now authorized. "
                    f"Scopes: {safe_status.get('scope') or 'standard'}. "
                    "You may safely close this browser tab."
                ),
            ),
            status_code=status.HTTP_200_OK,
        )

    return {
        "status": "success",
        "message": "eClinicalWorks Patient App OAuth 2.0 authorization completed successfully.",
        "token_type": safe_status.get("token_type", "Bearer"),
        "expires_in": safe_status.get("expires_in_seconds", 3600),
        "scope": safe_status.get("scope"),
        "has_refresh_token": safe_status.get("has_refresh_token", False),
        "patient_context": safe_status.get("patient_context"),
        "authorized_at": safe_status.get("last_authorized_at"),
    }


@router.get(
    "/patient/token-status",
    summary="Patient App OAuth Token Status Diagnostics",
    description="Returns safe metadata about the stored Patient App OAuth token without exposing secrets.",
)
@router.get(
    "/token-status",
    summary="OAuth Token Status Diagnostics (Alias)",
    description="Alias for /api/ecw/patient/token-status.",
)
async def get_patient_token_status() -> Dict[str, Any]:
    """Return safe status of currently stored Patient App OAuth tokens."""
    status_info = ecw_patient_token_store.get_safe_status()
    status_info["client_id_configured"] = bool(settings.ECW_PATIENT_CLIENT_ID)
    status_info["client_secret_configured"] = bool(settings.ECW_PATIENT_CLIENT_SECRET)
    status_info["redirect_uri"] = settings.ECW_PATIENT_REDIRECT_URI
    status_info["token_url"] = settings.ECW_PATIENT_TOKEN_URL
    status_info["practice_code"] = settings.ECW_PATIENT_PRACTICE_CODE
    status_info["pending_auth_states"] = ecw_patient_state_store.count()
    return status_info


@router.get(
    "/provider/token-status",
    summary="Provider App Token Cache Status",
    description="Returns safe metadata about the cached Provider App Backend Services access token without exposing secrets.",
    tags=["eCW Provider Scheduling"],
)
async def get_provider_token_status() -> Dict[str, Any]:
    """Return safe metadata of cached Provider App token."""
    return await ecw_client.get_provider_token_cache_status()


@router.get(
    "/scheduling/test",
    summary="Test eCW Provider App Scheduling API Access",
    description=(
        "Reuses existing Provider App Backend Services authentication (RFC 7523 private-key JWT) "
        "to acquire/verify access token and probe connectivity to eCW FHIR Scheduling resources (Slot, Appointment, Schedule).\n\n"
        "Performs scope diagnosis and tests official eCW FHIR scheduling endpoint without exposing tokens or credentials."
    ),
    tags=["eCW Provider Scheduling"],
)
async def test_ecw_scheduling_alias(
    resource: str = Query("Slot", description="FHIR Scheduling resource: Slot, Appointment, or Schedule"),
    count: int = Query(5, ge=1, le=50, description="Max records to probe in FHIR bundle"),
) -> Dict[str, Any]:
    """Test eCW FHIR Scheduling resource access using the Provider App access token."""
    return await ecw_client.test_scheduling_access(resource=resource, query_params={"_count": str(count)})


@router.post(
    "/patient/refresh",
    summary="Refresh Stored Patient App OAuth Token",
    description="Attempts to refresh the active access token using the stored refresh token.",
)
async def refresh_patient_token() -> Dict[str, Any]:
    """Refresh active Patient App access token using stored refresh token."""
    safe_status = await ecw_patient_auth_service.refresh_access_token()
    return {
        "status": "refreshed",
        "message": "Patient App OAuth access token refreshed successfully.",
        "token_status": safe_status,
    }


@router.post(
    "/patient/clear-token",
    summary="Clear Stored Patient App OAuth Tokens",
    description="Resets and removes stored Patient App OAuth tokens from backend memory.",
)
async def clear_stored_patient_tokens() -> Dict[str, Any]:
    """Clear all stored Patient App OAuth tokens."""
    ecw_patient_token_store.clear_tokens()
    return {
        "status": "cleared",
        "message": "Stored Patient App OAuth tokens cleared successfully.",
    }


def _render_html_status(title: str, is_success: bool, message: str, detail: str) -> str:
    """Render a clean, secure HTML confirmation page for browser authorization flows."""
    color = "#10b981" if is_success else "#ef4444"
    icon = "&#10004;" if is_success else "&#10008;"
    status_label = "Success" if is_success else "Attention Required"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — {settings.CLINIC_NAME}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: #0f172a;
      color: #f8fafc;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 1.5rem;
    }}
    .card {{
      background-color: #1e293b;
      border: 1px solid #334155;
      border-radius: 1rem;
      max-width: 32rem;
      width: 100%;
      padding: 2.5rem;
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
      text-align: center;
    }}
    .icon {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 4.5rem;
      height: 4.5rem;
      border-radius: 9999px;
      background-color: rgba({('16, 185, 129' if is_success else '239, 68, 68')}, 0.15);
      color: {color};
      font-size: 2.25rem;
      margin-bottom: 1.5rem;
    }}
    .badge {{
      display: inline-block;
      font-size: 0.75rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      padding: 0.25rem 0.75rem;
      border-radius: 9999px;
      background-color: rgba({('16, 185, 129' if is_success else '239, 68, 68')}, 0.2);
      color: {color};
      margin-bottom: 0.75rem;
    }}
    h1 {{ font-size: 1.5rem; font-weight: 700; margin-bottom: 0.75rem; }}
    p.message {{ font-size: 1.05rem; color: #cbd5e1; margin-bottom: 1rem; }}
    p.detail {{ font-size: 0.875rem; color: #94a3b8; line-height: 1.5; }}
    .footer {{ margin-top: 2rem; font-size: 0.75rem; color: #64748b; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">{icon}</div>
    <div><span class="badge">{status_label}</span></div>
    <h1>{title}</h1>
    <p class="message">{message}</p>
    <p class="detail">{detail}</p>
    <div class="footer">
      {settings.CLINIC_NAME} &bull; AI Receptionist &bull; eClinicalWorks SMART on FHIR
    </div>
  </div>
</body>
</html>"""
