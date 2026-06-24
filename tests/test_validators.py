# tests/test_validators.py
"""Tests for input validation utilities, specifically Facebook group normalization."""

import pytest
from utils.validators import normalize_facebook_group_url


def test_normalize_facebook_group_url_success():
    """Test that valid Facebook group URLs are correctly normalized and canonicalised."""
    test_cases = [
        # (input_url, expected_normalized, expected_canonical_id)
        (
            "https://www.facebook.com/groups/101875683484689",
            "https://www.facebook.com/groups/101875683484689/",
            "101875683484689"
        ),
        (
            "https://www.facebook.com/groups/101875683484689/",
            "https://www.facebook.com/groups/101875683484689/",
            "101875683484689"
        ),
        (
            "http://facebook.com/groups/35819517694",
            "https://www.facebook.com/groups/35819517694/",
            "35819517694"
        ),
        (
            "https://m.facebook.com/groups/apartments.tlv?ref=share",
            "https://www.facebook.com/groups/apartments.tlv/",
            "apartments.tlv"
        ),
        (
            "facebook.com/groups/some-slug-12345/",
            "https://www.facebook.com/groups/some-slug-12345/",
            "some-slug-12345"
        ),
        (
            "https://www.facebook.com/share/g/18m6GA3j8x/",
            "https://www.facebook.com/share/g/18m6GA3j8x/",
            "share-g-18m6ga3j8x"
        ),
        (
            "http://fb.com/groups/123",
            "https://www.facebook.com/groups/123/",
            "123"
        ),
    ]
    
    for input_url, expected_norm, expected_canon in test_cases:
        is_valid, norm, canon, err = normalize_facebook_group_url(input_url)
        assert is_valid is True, f"Failed on {input_url}: {err}"
        assert norm == expected_norm, f"Incorrect normalization for {input_url}. Got: {norm}"
        assert canon == expected_canon, f"Incorrect canonical ID for {input_url}. Got: {canon}"


def test_normalize_facebook_group_url_failure():
    """Test that invalid URLs and non-group links are correctly rejected."""
    failure_cases = [
        # (input_url, expected_error_substring)
        ("", "ריקה"),
        ("https://google.com", "לקבוצת פייסבוק"),
        ("https://www.facebook.com/groups/", "לא נמצא מזהה קבוצה תקין"),
        ("https://www.facebook.com/groups/101875683484689/permalink/123456/", "זה נראה כמו קישור לפוסט"),
        ("https://www.facebook.com/groups/101875683484689/posts/123456/", "זה נראה כמו קישור לפוסט"),
        ("https://www.facebook.com/some_user", "לא נמצא מזהה קבוצה תקין"),
    ]
    
    for input_url, err_sub in failure_cases:
        is_valid, norm, canon, err = normalize_facebook_group_url(input_url)
        assert is_valid is False, f"Should have failed on: {input_url}"
        assert err_sub in err, f"Expected '{err_sub}' in error message '{err}' for {input_url}"
