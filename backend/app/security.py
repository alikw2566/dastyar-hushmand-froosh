from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, text

from .config import get_settings
from .database import SessionFactory
from .models import Membership, Role

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    subject: str
    email: str
    tenant_id: UUID
    role: Role


@lru_cache
def jwks_client() -> jwt.PyJWKClient:
    settings = get_settings()
    url = settings.oidc_jwks_url or f"{settings.oidc_issuer}/protocol/openid-connect/certs"
    return jwt.PyJWKClient(url)


async def current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    settings = get_settings()
    if settings.auth_disabled and settings.environment == "development":
        return Principal(
            subject="local-admin",
            email="admin@mokalemeban.local",
            tenant_id=UUID(settings.development_tenant_id),
            role=Role.admin,
        )
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication_required"
        )
    try:
        key = jwks_client().get_signing_key_from_jwt(credentials.credentials).key
        claims = jwt.decode(
            credentials.credentials,
            key=key,
            algorithms=["RS256"],
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
        )
        tenant_id = UUID(claims["tenant_id"])
        realm_roles = claims.get("realm_access", {}).get("roles", [])
        role_value = claims.get("role") or next(
            (
                value
                for value in ("admin", "manager", "supervisor", "agent", "seller", "viewer")
                if value in realm_roles
            ),
            "viewer",
        )
        role = Role(role_value)
    except (KeyError, ValueError, jwt.PyJWTError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token"
        ) from exc
    email = claims.get("email", claims["sub"]).strip().lower()
    async with SessionFactory() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
        membership = await session.scalar(
            select(Membership).where(
                Membership.tenant_id == tenant_id,
                Membership.email == email,
            )
        )
        if membership is None or not membership.active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="membership_inactive_or_missing",
            )
        role = membership.role
    return Principal(
        subject=claims["sub"],
        email=email,
        tenant_id=tenant_id,
        role=role,
    )


def require_roles(*allowed: Role):
    async def dependency(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
        if principal.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient_role")
        return principal

    return dependency
