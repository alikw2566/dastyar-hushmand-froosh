"""Small idempotent Keycloak Admin API client used for tenant provisioning."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from ..config import get_settings


class KeycloakAdmin:
    def __init__(self, client_factory: Callable[..., httpx.AsyncClient] | None = None):
        self.settings = get_settings()
        self.client_factory = client_factory or httpx.AsyncClient

    async def _token(self, client: httpx.AsyncClient, base: str) -> str:
        response = await client.post(
            f"{base}/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": self.settings.keycloak_admin_user,
                "password": self.settings.keycloak_admin_password,
            },
        )
        response.raise_for_status()
        return response.json()["access_token"]

    async def health(self) -> bool:
        base = self.settings.keycloak_admin_url.rstrip("/")
        async with self.client_factory(timeout=5) as client:
            response = await client.get(
                f"{base}/realms/{self.settings.keycloak_realm}/.well-known/openid-configuration"
            )
            response.raise_for_status()
        return True

    async def _find_user_id(
        self, client: httpx.AsyncClient, base: str, headers: dict, email: str
    ) -> str:
        response = await client.get(
            f"{base}/admin/realms/{self.settings.keycloak_realm}/users",
            headers=headers,
            params={"username": email, "exact": "true"},
        )
        response.raise_for_status()
        users = response.json()
        if not users:
            raise RuntimeError("keycloak user was created but could not be resolved")
        return users[0]["id"]

    async def _ensure_tenant_mapper(
        self, client: httpx.AsyncClient, base: str, headers: dict
    ) -> None:
        clients_response = await client.get(
            f"{base}/admin/realms/{self.settings.keycloak_realm}/clients",
            headers=headers,
            params={"clientId": self.settings.oidc_audience},
        )
        clients_response.raise_for_status()
        clients = clients_response.json()
        if not clients:
            raise RuntimeError(f"Keycloak client not found: {self.settings.oidc_audience}")
        client_uuid = clients[0]["id"]
        endpoint = (
            f"{base}/admin/realms/{self.settings.keycloak_realm}/clients/"
            f"{client_uuid}/protocol-mappers/models"
        )
        existing_response = await client.get(endpoint, headers=headers)
        existing_response.raise_for_status()
        if any(item.get("name") == "tenant_id" for item in existing_response.json()):
            return
        response = await client.post(
            endpoint,
            headers=headers,
            json={
                "name": "tenant_id",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-usermodel-attribute-mapper",
                "config": {
                    "user.attribute": "tenant_id",
                    "claim.name": "tenant_id",
                    "jsonType.label": "String",
                    "id.token.claim": "true",
                    "access.token.claim": "true",
                    "userinfo.token.claim": "true",
                    "multivalued": "false",
                },
            },
        )
        if response.status_code not in (201, 409):
            response.raise_for_status()

    async def create_user(
        self,
        email: str,
        display_name: str,
        password: str,
        *,
        tenant_id: str | None = None,
        realm_role: str | None = None,
    ) -> None:
        base = self.settings.keycloak_admin_url.rstrip("/")
        async with self.client_factory(timeout=15) as client:
            token = await self._token(client, base)
            headers = {"authorization": f"Bearer {token}"}
            payload = {
                "username": email,
                "email": email,
                "firstName": display_name,
                "enabled": True,
                "emailVerified": False,
                "credentials": [{"type": "password", "value": password, "temporary": True}],
                "requiredActions": ["UPDATE_PASSWORD"],
            }
            if tenant_id:
                payload["attributes"] = {"tenant_id": [tenant_id]}
            response = await client.post(
                f"{base}/admin/realms/{self.settings.keycloak_realm}/users",
                headers=headers,
                json=payload,
            )
            if response.status_code not in (201, 409):
                response.raise_for_status()
            user_id = await self._find_user_id(client, base, headers, email)
            if tenant_id:
                user_response = await client.get(
                    f"{base}/admin/realms/{self.settings.keycloak_realm}/users/{user_id}",
                    headers=headers,
                )
                user_response.raise_for_status()
                user_data = user_response.json()
                existing_tenants = list((user_data.get("attributes") or {}).get("tenant_id", []))
                if existing_tenants and tenant_id not in existing_tenants:
                    raise RuntimeError("keycloak_user_belongs_to_another_tenant")
                attributes = dict(user_data.get("attributes") or {})
                attributes["tenant_id"] = [tenant_id]
                update_response = await client.put(
                    f"{base}/admin/realms/{self.settings.keycloak_realm}/users/{user_id}",
                    headers=headers,
                    json={**user_data, "attributes": attributes, "enabled": True},
                )
                update_response.raise_for_status()
                await self._ensure_tenant_mapper(client, base, headers)
            if realm_role:
                role_response = await client.get(
                    f"{base}/admin/realms/{self.settings.keycloak_realm}/roles/{realm_role}",
                    headers=headers,
                )
                role_response.raise_for_status()
                mapping_response = await client.post(
                    f"{base}/admin/realms/{self.settings.keycloak_realm}/users/{user_id}/role-mappings/realm",
                    headers=headers,
                    json=[role_response.json()],
                )
                if mapping_response.status_code not in (204, 409):
                    mapping_response.raise_for_status()

    async def update_user_access(
        self,
        email: str,
        *,
        tenant_id: str,
        realm_role: str,
        enabled: bool,
    ) -> None:
        base = self.settings.keycloak_admin_url.rstrip("/")
        managed_roles = {"admin", "manager", "supervisor", "agent", "seller", "viewer"}
        async with self.client_factory(timeout=15) as client:
            token = await self._token(client, base)
            headers = {"authorization": f"Bearer {token}"}
            user_id = await self._find_user_id(client, base, headers, email)
            endpoint = f"{base}/admin/realms/{self.settings.keycloak_realm}/users/{user_id}"
            response = await client.get(endpoint, headers=headers)
            response.raise_for_status()
            data = response.json()
            existing_tenants = list((data.get("attributes") or {}).get("tenant_id", []))
            if existing_tenants != [tenant_id]:
                raise RuntimeError("keycloak_tenant_mismatch")
            update = await client.put(endpoint, headers=headers, json={**data, "enabled": enabled})
            update.raise_for_status()
            mapping_url = f"{endpoint}/role-mappings/realm"
            mappings = await client.get(mapping_url, headers=headers)
            mappings.raise_for_status()
            removable = [row for row in mappings.json() if row.get("name") in managed_roles]
            if removable:
                removed = await client.request(
                    "DELETE", mapping_url, headers=headers, json=removable
                )
                removed.raise_for_status()
            role_response = await client.get(
                f"{base}/admin/realms/{self.settings.keycloak_realm}/roles/{realm_role}",
                headers=headers,
            )
            role_response.raise_for_status()
            assigned = await client.post(mapping_url, headers=headers, json=[role_response.json()])
            if assigned.status_code not in (204, 409):
                assigned.raise_for_status()


keycloak_admin = KeycloakAdmin()
