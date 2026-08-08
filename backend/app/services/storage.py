import asyncio
from pathlib import Path
from uuid import UUID

import boto3
from botocore.config import Config

from ..config import get_settings


class ObjectStorage:
    def __init__(self):
        settings = get_settings()
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4"),
        )

    async def ensure_bucket(self) -> None:
        def ensure():
            existing = [item["Name"] for item in self.client.list_buckets().get("Buckets", [])]
            if self.bucket not in existing:
                self.client.create_bucket(Bucket=self.bucket)

        await asyncio.to_thread(ensure)

    async def upload(
        self, tenant_id: UUID, call_id: UUID, file_name: str, content_type: str, body
    ) -> str:
        safe_name = "".join(char if char.isalnum() or char in "._-" else "_" for char in file_name)
        key = f"{tenant_id}/{call_id}/{safe_name}"
        await asyncio.to_thread(
            self.client.upload_fileobj,
            body,
            self.bucket,
            key,
            ExtraArgs={
                "ContentType": content_type,
                "Metadata": {"tenant-id": str(tenant_id), "call-id": str(call_id)},
            },
        )
        return key

    async def download(self, key: str, destination: Path) -> None:
        await asyncio.to_thread(self.client.download_file, self.bucket, key, str(destination))

    async def signed_url(self, key: str, expires_seconds: int = 900) -> str:
        return await asyncio.to_thread(
            self.client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )

    async def head(self, key: str) -> dict:
        return await asyncio.to_thread(self.client.head_object, Bucket=self.bucket, Key=key)

    async def open_stream(self, key: str, byte_range: str | None = None):
        params = {"Bucket": self.bucket, "Key": key}
        if byte_range:
            params["Range"] = byte_range
        return await asyncio.to_thread(self.client.get_object, **params)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)

    async def health(self) -> bool:
        await asyncio.to_thread(self.client.head_bucket, Bucket=self.bucket)
        return True


storage = ObjectStorage()
