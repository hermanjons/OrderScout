from __future__ import annotations

from typing import Optional

from sqlmodel import Field, SQLModel
from Core.db.models import SourceIdentityMixin


class AiModelArtifact(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "ai_model_artifact"

    pk: Optional[int] = Field(default=None, primary_key=True)
    repo_id: str = Field(index=True, max_length=255)
    filename: str = Field(index=True, max_length=255)
    display_name: Optional[str] = Field(default=None, max_length=255)
    file_format: Optional[str] = Field(default=None, max_length=64)
    quantization: Optional[str] = Field(default=None, max_length=64)
    size_bytes: Optional[int] = Field(default=None)
    local_path: str = Field(max_length=1024)
    download_root: str = Field(max_length=1024)
    source_url: Optional[str] = Field(default=None, max_length=1024)
    etag: Optional[str] = Field(default=None, max_length=255)
    exists_on_disk: bool = Field(default=True)


class AiProviderAccount(SourceIdentityMixin, SQLModel, table=True):
    __tablename__ = "ai_provider_account"

    pk: Optional[int] = Field(default=None, primary_key=True)
    provider_code: str = Field(index=True, max_length=64)
    label: str = Field(index=True, max_length=255)
    endpoint_url: Optional[str] = Field(default=None, max_length=512)
    api_key: str = Field(max_length=2048)
    default_model: Optional[str] = Field(default=None, max_length=255)
    is_enabled: bool = Field(default=True)
