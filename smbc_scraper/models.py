# smbc_scraper/models.py

from __future__ import annotations

import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ComicRow(BaseModel):
    """
    Represents a single row of scraped comic data.
    Each source will populate a subset of these fields.
    """

    url: str = Field(description="Canonical URL for the comic.")

    slug: str = Field(
        description=(
            "Unique identifier, usually the date slug from the URL "
            "(e.g., '2025-09-13')."
        )
    )

    legacy_id: int | None = Field(
        None,
        description="The legacy numeric ID of the comic, if available.",
    )

    comic_text: str | None = Field(
        None,
        description=(
            "Transcript of the main comic text, sourced from wiki or ohnorobot."
        ),
    )

    hover_text: str | None = Field(
        None,
        description="The hover text (title/alt attribute) from the main comic image.",
    )

    votey_text: str | None = Field(
        None,
        description=(
            "Text from the bonus 'votey' panel, either hover text or transcript."
        ),
    )

    date: datetime.date | None = Field(
        None, description="The publication date of the comic."
    )

    page_title: str | None = Field(
        None, description="The <title> of the comic's HTML page."
    )

    # --- Source-specific metadata ---
    source: str = Field(
        description=(
            "The source identifier where this data was scraped from "
            "(e.g., 'smbc', 'wiki')."
        )
    )

    # Example of a source-specific field, as mentioned in the spec
    transcript_quality: str | None = Field(
        None, description="Flag for wiki transcripts (e.g., 'auto' or 'manual')."
    )
    model_config = ConfigDict(from_attributes=True)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be an absolute http(s) URL")
        return value
