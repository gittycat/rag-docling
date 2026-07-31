"""The GLiNER recognizer closes the detector gaps spaCy leaves open.

Opt-in and slow: needs `uv sync --extra gliner` and downloads ~200MB on first
run, so these are skipped unless the package is present. They pin the two cases
that justify the option existing — separator-joined names in filenames (the
strict xfail in test_pii_metadata.py) and phone numbers, which Presidio's spaCy
backend scores poorly on.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from infrastructure.config.models_config import PiiConfig, PiiGlinerConfig
from infrastructure.pii.service import PIIMaskingService

pytest.importorskip("gliner", reason="requires the optional gliner extra")

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def gliner_service():
    return PIIMaskingService(
        PiiConfig(enabled=True, gliner=PiiGlinerConfig(enabled=True, map_location="cpu"))
    )


@pytest.fixture(scope="module")
def spacy_service():
    return PIIMaskingService(PiiConfig(enabled=True))


def test_separator_joined_name_in_filename_is_masked(gliner_service, spacy_service):
    filename = "Jane_Doe_severance_2025.pdf"

    # Documents the gap this option exists to close.
    assert "Jane" in spacy_service.mask(filename).masked_text

    masked = gliner_service.mask(filename).masked_text
    assert "Jane" not in masked
    assert "Doe" not in masked
    assert masked.endswith(".pdf")


def test_phone_number_is_masked(gliner_service):
    masked = gliner_service.mask("Call Maria Gonzalez on 555-241-9987 about invoice 44821").masked_text

    assert "555-241-9987" not in masked
    assert "Maria Gonzalez" not in masked
    assert "44821" in masked  # invoice number is not PII


def test_regex_entities_still_recognized(gliner_service):
    """GLiNER is registered alongside the pattern recognizers, not instead of them."""
    masked = gliner_service.mask("Contact John Smith at john@example.com").masked_text

    assert "john@example.com" not in masked
    assert "John Smith" not in masked


def test_masking_stays_reversible_with_gliner(gliner_service):
    original = "Jane_Doe_severance_2025.pdf"
    result = gliner_service.mask(original)

    assert gliner_service.unmask(result.masked_text, result.token_mapping).unmasked_text == original
