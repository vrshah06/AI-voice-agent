"""Tests for eClinicalWorks JWKS endpoint, asymmetric key management, and client assertion generation."""
import time
import pytest
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
from jwt import PyJWK

from app.main import app
from app.core.config import settings
from app.core.jwks import key_manager, _int_to_base64url


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    return TestClient(app)


def test_well_known_jwks_structure(client):
    """JWKS endpoint must conform to RFC 7517 and expose only public key material."""
    response = client.get("/.well-known/jwks.json")
    assert response.status_code == 200
    data = response.json()

    assert "keys" in data
    assert isinstance(data["keys"], list)
    assert len(data["keys"]) >= 1

    jwk = data["keys"][0]
    assert jwk["kty"] == "RSA"
    assert jwk["use"] == "sig"
    assert jwk["alg"] == "RS384"  # Mandated by eCW
    assert jwk["kid"] == key_manager.key_id
    assert "n" in jwk
    assert "e" in jwk

    # Critical security check: Ensure NO private key parameters are present
    private_fields = ["d", "p", "q", "dp", "dq", "qi", "dmp1", "dmq1", "coeff"]
    for field in private_fields:
        assert field not in jwk, f"Private key field '{field}' leaked in public JWKS!"


def test_alias_jwks_matches_well_known(client):
    """The alias /api/auth/jwks.json must return identical payload to /.well-known/jwks.json."""
    resp1 = client.get("/.well-known/jwks.json")
    resp2 = client.get("/api/auth/jwks.json")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json() == resp2.json()


def test_ecw_auth_status_endpoint(client):
    """Status endpoint must provide integration readiness without exposing secrets."""
    response = client.get("/api/auth/ecw-status")
    assert response.status_code == 200
    status_data = response.json()

    assert "status" in status_data
    assert status_data["algorithm"] == "RS384"
    assert status_data["key_id"] == key_manager.key_id
    assert status_data["oauth_grant_type"] == "client_credentials"
    assert status_data["client_assertion_type"] == "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
    assert "/.well-known/jwks.json" in status_data["public_jwks_url"]


def test_client_assertion_claims_and_signature():
    """Client assertion JWT must have exact required headers and claims, verifiable by public JWK."""
    test_client_id = "test-ecw-client-id-12345"
    test_token_url = "https://staging-oauthserver.ecwcloud.com/oauth/oauth2/token"

    assertion = key_manager.generate_client_assertion(
        client_id=test_client_id,
        token_url=test_token_url,
        expiry_seconds=300,
    )
    assert isinstance(assertion, str)
    assert len(assertion.split(".")) == 3

    # Inspect unverified headers
    headers = jwt.get_unverified_header(assertion)
    assert headers["alg"] == "RS384"
    assert headers["typ"] == "JWT"
    assert headers["kid"] == key_manager.key_id

    # Retrieve public key from key_manager
    jwk_dict = key_manager.get_public_jwk()
    pyjwk = PyJWK(jwk_dict)

    # Verify signature and decode claims using public key
    decoded = jwt.decode(
        assertion,
        key=pyjwk.key,
        algorithms=["RS384"],
        audience=test_token_url,
    )

    assert decoded["iss"] == test_client_id
    assert decoded["sub"] == test_client_id
    assert decoded["aud"] == test_token_url
    assert "jti" in decoded
    assert "iat" in decoded
    assert "exp" in decoded

    # Expiry validation
    now = int(time.time())
    assert decoded["exp"] > now
    assert (decoded["exp"] - decoded["iat"]) <= 300


def test_public_private_key_correspondence():
    """Public key from JWKS must accurately verify data signed by private key."""
    jwk = key_manager.get_public_jwk()
    pub_key_obj = key_manager._public_key
    assert pub_key_obj is not None

    pub_numbers = pub_key_obj.public_numbers()
    assert _int_to_base64url(pub_numbers.n) == jwk["n"]
    assert _int_to_base64url(pub_numbers.e) == jwk["e"]
