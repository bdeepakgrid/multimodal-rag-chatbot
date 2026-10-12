from enum import Enum
from dataclasses import dataclass
from typing import Optional
from fastapi import Request, HTTPException, Depends
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class Role(str, Enum):
    TECHNICIAN = "technician"
    REVIEWER = "reviewer"
    ADMIN = "admin"


@dataclass
class UserContext:
    tenant_id: str
    role: Role
    identity: str


API_KEY_STORE: dict[str, tuple[str, Role, str]] = {
    "tech-key-123": ("default", Role.TECHNICIAN, "technician"),
    "technician-key-123": ("default", Role.TECHNICIAN, "technician"),
    "reviewer-key-456": ("default", Role.REVIEWER, "reviewer"),
    "admin-key-789": ("default", Role.ADMIN, "admin"),
}


def resolve_legacy_api_key(token: str) -> Optional[UserContext]:
    record = API_KEY_STORE.get(token)
    if not record:
        return None
    tenant_id, role, identity = record
    return UserContext(tenant_id=tenant_id, role=role, identity=identity)


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Allow public endpoints (health, docs, login, signup)
        if (
            path in ["/health", "/docs", "/openapi.json", "/redoc"]
            or path.startswith("/api/v1/auth/login")
            or path.startswith("/api/v1/auth/signup")
            or not path.startswith("/api/")
        ):
            return await call_next(request)

        # Retrieve token from Authorization header or API-Key / X-API-Key header
        auth_header = request.headers.get("Authorization", "")
        token = None
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

        if not token:
            token = request.headers.get("API-Key") or request.headers.get("X-API-Key")

        user_ctx: Optional[UserContext] = None

        if token:
            from api.auth_db import resolve_token
            user_ctx = resolve_token(token) or resolve_legacy_api_key(token)

        if not user_ctx:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key or authentication token"}
            )

        request.state.user = user_ctx
        request.state.role = user_ctx.role
        request.state.tenant_id = user_ctx.tenant_id

        return await call_next(request)


def get_current_user(request: Request) -> UserContext:
    user: Optional[UserContext] = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_roles(*allowed: Role):
    """FastAPI dependency factory that enforces role-based access.

    Usage::

        @router.post("/ingest")
        async def ingest(user: UserContext = Depends(require_roles(Role.ADMIN))):
            ...

    Raises HTTP 403 if the authenticated user's role is not in *allowed*.
    """
    def _check(user: UserContext = Depends(get_current_user)) -> UserContext:
        if user.role not in allowed:
            allowed_names = ", ".join(r.value for r in allowed)
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Required role(s): {allowed_names}. Your role: {user.role.value}.",
            )
        return user

    return _check
