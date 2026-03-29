# test/test_models.py
from datetime import date

import pytest
from pydantic import ValidationError

from smbc_scraper.models import ComicRow


def test_comic_row_valid_url():
    row = ComicRow(
        url="https://www.smbc-comics.com/comic/test",
        slug="test",
        source="smbc"
    )
    assert row.url == "https://www.smbc-comics.com/comic/test"

def test_comic_row_invalid_url():
    with pytest.raises(ValidationError):
        ComicRow(
            url="not-a-url",
            slug="test",
            source="smbc"
        )

def test_comic_row_optional_fields():
    row = ComicRow(
        url="https://www.smbc-comics.com/comic/test",
        slug="test",
        source="smbc",
        date=date(2023, 10, 1),
        legacy_id=123,
        hover_text="hover",
        votey_text="votey",
        page_title="Title"
    )
    assert row.date == date(2023, 10, 1)
    assert row.legacy_id == 123
    assert row.hover_text == "hover"
    assert row.votey_text == "votey"
    assert row.page_title == "Title"
