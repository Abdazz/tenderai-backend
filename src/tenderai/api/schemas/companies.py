"""Pydantic schemas for Company API."""

from datetime import datetime

from pydantic import BaseModel, Field


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=64)
    logo_url: str | None = None
    subject_prefix: str | None = Field(None, max_length=100)
    signature: str | None = Field(None, max_length=255)


class CompanyUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    active: bool | None = None
    logo_url: str | None = None
    subject_prefix: str | None = Field(None, max_length=100)
    signature: str | None = Field(None, max_length=255)


class CompanyRead(BaseModel):
    id: int
    name: str
    slug: str
    active: bool
    logo_url: str | None = None
    subject_prefix: str | None = None
    signature: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CompanyCountrySubscriptionCreate(BaseModel):
    country_id: int


class CompanyCountrySubscriptionRead(BaseModel):
    company_id: int
    country_id: int
    enabled: bool
    created_at: datetime

    model_config = {"from_attributes": True}
