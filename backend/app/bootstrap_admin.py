"""Idempotent first-tenant/first-admin bootstrap command."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import select

from .database import tenant_session
from .models import Membership, Organization, Role
from .services.keycloak import keycloak_admin


@dataclass(frozen=True, slots=True)
class FirstAdminConfig:
    email: str
    password: str
    name: str
    tenant_name: str
    tenant_id: uuid.UUID


def parse_bootstrap_environment(environment: Mapping[str, str]) -> FirstAdminConfig | None:
    values = {
        "email": environment.get("FIRST_ADMIN_EMAIL", "").strip().lower(),
        "password": environment.get("FIRST_ADMIN_PASSWORD", ""),
        "name": environment.get("FIRST_ADMIN_NAME", "").strip(),
        "tenant_name": environment.get("DEFAULT_TENANT_NAME", "").strip(),
    }
    if not any(values.values()):
        return None
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise ValueError(f"missing bootstrap environment values: {', '.join(missing)}")
    if "@" not in values["email"] or "." not in values["email"].rsplit("@", 1)[-1]:
        raise ValueError("FIRST_ADMIN_EMAIL is invalid")
    if len(values["password"]) < 12:
        raise ValueError("FIRST_ADMIN_PASSWORD must be at least 12 characters")
    configured_tenant_id = environment.get("DEFAULT_TENANT_ID", "").strip()
    if configured_tenant_id:
        try:
            tenant_id = uuid.UUID(configured_tenant_id)
        except ValueError as exc:
            raise ValueError("DEFAULT_TENANT_ID must be a valid UUID") from exc
    else:
        tenant_id = uuid.uuid5(
            uuid.NAMESPACE_DNS, f"mokalemeban:{values['tenant_name'].casefold()}"
        )
    return FirstAdminConfig(tenant_id=tenant_id, **values)


async def bootstrap(config: FirstAdminConfig) -> str:
    await keycloak_admin.create_user(
        config.email,
        config.name,
        config.password,
        tenant_id=str(config.tenant_id),
        realm_role="admin",
    )
    async for session in tenant_session(str(config.tenant_id)):
        organization = await session.scalar(
            select(Organization).where(Organization.id == config.tenant_id)
        )
        if organization is None:
            session.add(Organization(id=config.tenant_id, name=config.tenant_name, plan="free"))
            await session.flush()
        membership = await session.scalar(
            select(Membership).where(
                Membership.tenant_id == config.tenant_id,
                Membership.email == config.email,
            )
        )
        if membership is None:
            session.add(
                Membership(
                    tenant_id=config.tenant_id,
                    email=config.email,
                    display_name=config.name,
                    role=Role.admin,
                    active=True,
                )
            )
            result = "created"
        else:
            membership.display_name = config.name
            membership.role = Role.admin
            membership.active = True
            result = "already_exists"
        await session.commit()
        return result
    raise RuntimeError("database session unavailable")


async def _main() -> int:
    try:
        config = parse_bootstrap_environment(os.environ)
    except ValueError as exc:
        print(f"First admin was not created: {exc}", file=sys.stderr)
        return 2
    if config is None:
        print(
            "First admin was not created. Set FIRST_ADMIN_EMAIL, FIRST_ADMIN_PASSWORD, "
            "FIRST_ADMIN_NAME and DEFAULT_TENANT_NAME."
        )
        return 0
    result = await bootstrap(config)
    print(f"First admin bootstrap: {result}; tenant_id={config.tenant_id}; email={config.email}")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
