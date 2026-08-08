from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.bootstrap_admin import parse_bootstrap_environment
from app.config import Settings
from app.services.keycloak import KeycloakAdmin
from app.tasks import celery_app


def production_settings(**overrides):
    values = {
        "_env_file": None,
        "environment": "production",
        "auth_disabled": False,
        "database_url": "postgresql+asyncpg://service:strong-value@postgres/prod",
        "s3_secret_key": "strong-s3-secret",
        "keycloak_admin_password": "strong-keycloak-secret",
        "secret_encryption_key": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    }
    values.update(overrides)
    return Settings(**values)


def test_production_configuration_rejects_insecure_defaults():
    with pytest.raises(ValidationError, match="insecure production configuration"):
        Settings(_env_file=None, environment="production")
    with pytest.raises(ValidationError, match="AUTH_DISABLED"):
        production_settings(auth_disabled=True)
    assert production_settings().environment == "production"
    configured = Settings(_env_file=None, processing_stage_timeout_seconds=90)
    assert configured.processing_stage_timeout_seconds == 90
    assert celery_app.conf.task_time_limit > celery_app.conf.task_soft_time_limit


def test_first_admin_environment_validation_and_stable_tenant_id():
    assert parse_bootstrap_environment({}) is None
    with pytest.raises(ValueError, match="missing bootstrap"):
        parse_bootstrap_environment({"FIRST_ADMIN_EMAIL": "admin@example.com"})
    values = {
        "FIRST_ADMIN_EMAIL": "ADMIN@example.com",
        "FIRST_ADMIN_PASSWORD": "a-strong-password",
        "FIRST_ADMIN_NAME": "مدیر سیستم",
        "DEFAULT_TENANT_NAME": "شرکت نمونه واقعی",
    }
    first = parse_bootstrap_environment(values)
    second = parse_bootstrap_environment(values)
    assert first.email == "admin@example.com"
    assert first.tenant_id == second.tenant_id
    configured = parse_bootstrap_environment(
        {**values, "DEFAULT_TENANT_ID": "11111111-1111-4111-8111-111111111111"}
    )
    assert str(configured.tenant_id) == "11111111-1111-4111-8111-111111111111"
    with pytest.raises(ValueError, match="DEFAULT_TENANT_ID"):
        parse_bootstrap_environment({**values, "DEFAULT_TENANT_ID": "not-a-uuid"})


def test_keycloak_realm_requires_totp_and_compose_uses_persistent_database():
    root = Path(__file__).parents[2]
    realm = json.loads(
        (root / "deploy" / "keycloak" / "mokalemeban-realm.json").read_text(encoding="utf-8")
    )
    totp = next(item for item in realm["requiredActions"] if item["alias"] == "CONFIGURE_TOTP")
    assert totp["enabled"] is True
    assert totp["defaultAction"] is True
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    assert "keycloak-postgres-data:/var/lib/postgresql/data" in compose
    assert "KC_DB_URL: jdbc:postgresql://keycloak-postgres:5432/keycloak" in compose


@pytest.mark.asyncio
async def test_keycloak_existing_user_gets_tenant_mapper_and_admin_role(monkeypatch):
    captured = {"user_payload": None, "updated_user": None, "role_mapping": None, "mapper": None}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        if path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "token"})
        if path.endswith("/users") and method == "POST":
            captured["user_payload"] = json.loads(request.content)
            return httpx.Response(409)
        if path.endswith("/users") and method == "GET":
            return httpx.Response(200, json=[{"id": "user-1"}])
        if path.endswith("/users/user-1") and method == "GET":
            return httpx.Response(
                200, json={"id": "user-1", "username": "admin@example.com", "attributes": {}}
            )
        if path.endswith("/users/user-1") and method == "PUT":
            captured["updated_user"] = json.loads(request.content)
            return httpx.Response(204)
        if path.endswith("/clients"):
            return httpx.Response(200, json=[{"id": "client-1"}])
        if path.endswith("/protocol-mappers/models") and method == "GET":
            return httpx.Response(200, json=[])
        if path.endswith("/protocol-mappers/models") and method == "POST":
            captured["mapper"] = json.loads(request.content)
            return httpx.Response(201)
        if path.endswith("/roles/admin"):
            return httpx.Response(200, json={"id": "role-1", "name": "admin"})
        if path.endswith("/role-mappings/realm"):
            captured["role_mapping"] = json.loads(request.content)
            return httpx.Response(204)
        raise AssertionError(f"unexpected Keycloak request: {method} {path}")

    transport = httpx.MockTransport(handler)

    def client_factory(**kwargs):
        return httpx.AsyncClient(transport=transport, **kwargs)

    service = KeycloakAdmin(client_factory=client_factory)
    await service.create_user(
        "admin@example.com",
        "مدیر",
        "a-strong-password",
        tenant_id="11111111-1111-4111-8111-111111111111",
        realm_role="admin",
    )
    assert captured["user_payload"]["attributes"]["tenant_id"] == [
        "11111111-1111-4111-8111-111111111111"
    ]
    assert captured["updated_user"]["attributes"]["tenant_id"] == [
        "11111111-1111-4111-8111-111111111111"
    ]
    assert captured["mapper"]["config"]["claim.name"] == "tenant_id"
    assert captured["role_mapping"] == [{"id": "role-1", "name": "admin"}]
