import os
import threading
import time

import httpx
from fastmcp.server.auth import TokenVerifier
from fastmcp.server.auth.auth import AccessToken
from fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)

DEFAULT_PLANE_BASE_URL = "https://api.plane.so"

# Cache successful PAT validations so we do NOT call GET /users/me/ on every
# single MCP request. Each MCP tool call already spends Plane API rate-limit
# budget on the real API call; a per-request validation call DOUBLED that and,
# under a burst, tripped the 60/min ApiKeyRateThrottle -> the validation got a
# 429, which the provider treated as "invalid token" -> 401 -> client sessions
# broke ("MCP not responding"). Caching collapses validation to ~once / TTL.
_VALIDATION_TTL_SECONDS = int(os.getenv("PLANE_PAT_VALIDATION_TTL", "120"))


class PlaneHeaderAuthProvider(TokenVerifier):
    def __init__(self, required_scopes: list[str] | None = None, timeout_seconds: int = 10):
        super().__init__(required_scopes=required_scopes)
        self.timeout_seconds = timeout_seconds
        # token -> expiry epoch for confirmed-valid PATs
        self._validated: dict[str, float] = {}
        self._lock = threading.Lock()

    def _cache_valid(self, token: str) -> bool:
        with self._lock:
            expiry = self._validated.get(token)
            if expiry and expiry > time.time():
                return True
            if expiry:
                self._validated.pop(token, None)
            return False

    def _cache_store(self, token: str) -> None:
        with self._lock:
            self._validated[token] = time.time() + _VALIDATION_TTL_SECONDS

    async def _validate_api_key(self, token: str) -> bool | None:
        """Validate the PAT against the Plane API.

        Returns:
            True  — confirmed valid (HTTP 200); safe to cache.
            None  — transient (HTTP 429 throttle or network error); allow the
                    request through WITHOUT caching. A 429 means "rate-limited",
                    not "invalid": failing auth here would turn a retryable
                    throttle into a session-killing 401. The real downstream API
                    call still enforces the token, so letting it through is safe.
            False — definitively invalid (401/403/other non-200); reject.
        """
        base_url = (
            os.getenv("PLANE_INTERNAL_BASE_URL") or os.getenv("PLANE_BASE_URL", DEFAULT_PLANE_BASE_URL)
        ).rstrip("/")
        user_url = f"{base_url}/api/v1/users/me/"

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(
                    user_url,
                    headers={"x-api-key": token, "Content-Type": "application/json"},
                )
            if response.status_code == 200:
                return True
            if response.status_code == 429:
                logger.warning(
                    "PAT validation throttled (429) — allowing request through; "
                    "the downstream Plane API call still enforces the token."
                )
                return None
            logger.warning("API key validation failed: %s", response.status_code)
            return False
        except httpx.RequestError as e:
            # Transient connectivity issue — don't break the session over it.
            logger.warning("API key validation request failed (allowing through): %s", e)
            return None

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            from fastmcp.server.dependencies import get_http_headers

            headers = get_http_headers()

            if token:
                workspace_slug = headers.get("x-workspace-slug")
                if not workspace_slug:
                    logger.warning("x-api-key header found but x-workspace-slug is missing")
                    return None

                if not self._cache_valid(token):
                    result = await self._validate_api_key(token)
                    if result is False:
                        logger.warning("API key validation against Plane API failed")
                        return None
                    if result is True:
                        self._cache_store(token)
                        logger.info("API key validated successfully via Plane API")
                    # result is None -> transient throttle/network: allow through, do not cache

                expires_at = int(time.time() + 3600)
                return AccessToken(
                    token=token,
                    client_id="api_key_header_user",
                    scopes=["read", "write"],
                    expires_at=expires_at,
                    claims={
                        "auth_method": "api_key_header",
                        "workspace_slug": workspace_slug,
                    },
                )
        except RuntimeError:
            # No active HTTP request available (e.g., stdio transport)
            logger.debug("No active HTTP request available for header check")
