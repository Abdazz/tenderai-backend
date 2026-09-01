"""Pydantic schemas for Country and CountrySettings API."""

from datetime import datetime

from pydantic import BaseModel, Field


class CountryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    code: str = Field(min_length=2, max_length=10)
    locale: str = Field(default="fr", min_length=2, max_length=10)


class CountryUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    locale: str | None = Field(None, min_length=2, max_length=10)
    active: bool | None = None


class CountryRead(BaseModel):
    id: int
    name: str
    code: str
    locale: str
    active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
