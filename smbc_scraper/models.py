# smbc_scraper/models.py

from __future__ import annotations

import datetime
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl, ConfigDict


class ComicRow(BaseModel):
    """
    Represents a single row of scraped comic data.
    Each source will populate a subset of these fields.
    """

    url: HttpUrl = Field(description="Canonical URL for the comic.")

    slug: str = Field(
        description="Unique identifier, usually the date slug from the URL (e.g., '2025-09-13')."
    )

    comic_text: Optional[str] = Field(
        None,
        description="Transcript of the main comic text, sourced from wiki or ohnorobot.",
    )

    hover_text: Optional[str] = Field(
        None,
        description="The hover text (title/alt attribute) from the main comic image.",
    )

    votey_text: Optional[str] = Field(
        None,
        description="Text from the bonus 'votey' panel, either hover text or transcript.",
    )

    date: Optional[datetime.date] = Field(
        None, description="The publication date of the comic."
    )

    page_title: Optional[str] = Field(
        None, description="The <title> of the comic's HTML page."
    )

    # --- Source-specific metadata ---
    source: str = Field(
        description="The source identifier where this data was scraped from (e.g., 'smbc', 'wiki')."
    )

    # Example of a source-specific field, as mentioned in the spec
    transcript_quality: Optional[str] = Field(
        None, description="Flag for wiki transcripts (e.g., 'auto' or 'manual')."
    )
    model_config = ConfigDict(from_attributes=True)
    # class Config:
    #     # Allows creating instances from ORM objects or dicts
    #     from_attributes = True
