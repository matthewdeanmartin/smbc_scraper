# tests/core/test_files.py

import datetime
from pathlib import Path

import pytest
from smbc_scraper.core.files import get_html_path, get_image_path
from smbc_scraper.models import ComicRow


@pytest.fixture
def comic_row_with_date() -> ComicRow:
    """Provides a ComicRow instance with a valid date."""
    return ComicRow(
        url="https://www.smbc-comics.com/comic/2025-09-13",
        slug="2025-09-13",
        date=datetime.date(2025, 9, 13),
        page_title="Test Comic",
        source="test-smbc",
    )


@pytest.fixture
def comic_row_no_date() -> ComicRow:
    """Provides a ComicRow instance with no date for fallback testing."""
    return ComicRow(
        url="https://www.smbc-comics.com/comic/a-weird-slug",
        slug="a-weird-slug",
        date=None,
        page_title="Another Test Comic",
        source="test-smbc",
    )


class TestGetImagePath:
    """Tests for the get_image_path function."""

    def test_get_image_path_with_date_and_extension(
        self, tmp_path: Path, comic_row_with_date: ComicRow
    ):
        """
        Verifies correct path construction for a main image with a date
        and a standard file extension.
        """
        image_url = "https://www.smbc-comics.com/comics/20250913.png"
        expected_path = (
            tmp_path
            / "images"
            / "2025"
            / "09"
            / "13"
            / "2025-09-13-main.png"
        )
        result_path = get_image_path(tmp_path, comic_row_with_date, image_url)
        assert result_path == expected_path

    def test_get_image_path_for_votey_image(
        self, tmp_path: Path, comic_row_with_date: ComicRow
    ):
        """
        Verifies correct path construction for a 'votey' image, checking for the '-votey' suffix.
        """
        image_url = "https://www.smbc-comics.com/comics/20250913-after.gif"
        expected_path = (
            tmp_path
            / "images"
            / "2025"
            / "09"
            / "13"
            / "2025-09-13-votey.gif"
        )
        result_path = get_image_path(
            tmp_path, comic_row_with_date, image_url, is_votey=True
        )
        assert result_path == expected_path

    def test_get_image_path_url_without_extension(
        self, tmp_path: Path, comic_row_with_date: ComicRow
    ):
        """
        Verifies that the function defaults to a '.png' extension when the image URL
        lacks one.
        """
        image_url = "https://images.example.com/some-image-path/image"
        expected_path = (
            tmp_path
            / "images"
            / "2025"
            / "09"
            / "13"
            / "2025-09-13-main.png"
        )
        result_path = get_image_path(tmp_path, comic_row_with_date, image_url)
        assert result_path == expected_path

    def test_get_image_path_returns_none_if_no_date(
        self, tmp_path: Path, comic_row_no_date: ComicRow
    ):
        """
        Verifies that the function returns None when the ComicRow has no date,
        as a structured path cannot be determined.
        """
        image_url = "https://www.smbc-comics.com/comics/some-image.png"
        result_path = get_image_path(tmp_path, comic_row_no_date, image_url)
        assert result_path is None


class TestGetHtmlPath:
    """Tests for the get_html_path function."""

    def test_get_html_path_with_date(
        self, tmp_path: Path, comic_row_with_date: ComicRow
    ):
        """
        Verifies correct, date-structured path construction for an HTML file.
        """
        expected_path = (
            tmp_path
            / "html"
            / "2025"
            / "09"
            / "13"
            / "2025-09-13.html"
        )
        result_path = get_html_path(tmp_path, comic_row_with_date)
        assert result_path == expected_path

    def test_get_html_path_fallback_without_date(
        self, tmp_path: Path, comic_row_no_date: ComicRow
    ):
        """
        Verifies that the path falls back to a 'misc' directory when the ComicRow
        lacks a date.
        """
        expected_path = tmp_path / "html" / "misc" / "a-weird-slug.html"
        result_path = get_html_path(tmp_path, comic_row_no_date)
        assert result_path == expected_path