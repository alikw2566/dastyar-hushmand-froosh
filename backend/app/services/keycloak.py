import httpx

from ..config import get_settings


class KeycloakAdmin:
    def __init__(self):
        self.settings = get_settings()

    async def create_user(self, email: str, display_name: str, password: str) -> None:
        base = self.settings.keycloak_admin_url.rstrip("/")
        async with httpx.AsyncClient(timeout=15) as client:
            token_response = await client.post(
                f"{base}/realms/master/protocol/openid-connect/token",
                data={
                    "grant_type": "password",
                    "client_id": "admin-cli",
                    "username": self.settings.keycloak_admin_user,
                    "password": self.settings.keycloak_admin_password,
                },
            )
            token_response.raise_for_status()
            token = token_response.json()["access_token"]
            response = await client.post(
                f"{base}/admin/realms/{self.settings.keycloak_realm}/users",
                headers={"authorization": f"Bearer {token}"},
                json={
                    "username": email,
                    "email": email,
                    "firstName": display_name,
                    "enabled": True,
                    "emailVerified": False,
                    "credentials": [{"type": "password", "value": password, "temporary": True}],
                    "requiredActions": ["UPDATE_PASSWORD"],
                },
            )
            if response.status_code not in (201, 409):
                response.raise_for_status()


keycloak_admin = KeycloakAdmin()
