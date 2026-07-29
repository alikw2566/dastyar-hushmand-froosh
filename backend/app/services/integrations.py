import json
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken

from ..config import get_settings


class Connector(Protocol):
    kind: str

    async def health(self) -> dict: ...
    async def sync_call(self, payload: dict) -> dict: ...


class SecretBox:
    def __init__(self):
        key = get_settings().secret_encryption_key
        self.fernet = Fernet(key.encode()) if key else None

    def encrypt(self, payload: dict) -> str:
        if not self.fernet:
            raise RuntimeError("SECRET_ENCRYPTION_KEY is required for integration credentials")
        return self.fernet.encrypt(json.dumps(payload).encode()).decode()

    def decrypt(self, value: str) -> dict:
        if not self.fernet:
            raise RuntimeError("SECRET_ENCRYPTION_KEY is required for integration credentials")
        try:
            return json.loads(self.fernet.decrypt(value.encode()).decode())
        except InvalidToken as exc:
            raise RuntimeError("integration credential could not be decrypted") from exc


class ConnectorRegistry:
    def __init__(self):
        self._factories: dict[str, type] = {}

    def register(self, kind: str, factory: type) -> None:
        if kind in self._factories:
            raise ValueError(f"connector already registered: {kind}")
        self._factories[kind] = factory

    def create(self, kind: str, config: dict) -> Connector:
        if kind not in self._factories:
            raise ValueError(f"unknown connector: {kind}")
        return self._factories[kind](config)


secret_box = SecretBox()
connector_registry = ConnectorRegistry()
