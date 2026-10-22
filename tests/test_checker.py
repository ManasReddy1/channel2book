"""Tests for the checker stage (quality report generation)."""

import pytest

from channel2book.models import CheckerClaim
from channel2book.stages.checker import generate_quality_report


def test_generate_quality_report():
    stats = {"total_claims": 5, "supported": 4, "unsupported": 1, "support_rate": 0.8}
    claims = {
        "vid1": [
            CheckerClaim(video_id="vid1", claim="Fact A", supported=True, confidence=0.9),
            CheckerClaim(video_id="vid1", claim="Fact B", supported=True, confidence=0.95),
            CheckerClaim(video_id="vid1", claim="Made up claim", supported=False, confidence=0.3),
        ],
    }
    report = generate_quality_report(stats, claims)
    assert report["total_claims"] == 5
    assert report["support_rate"] == 0.8
    assert len(report["flagged_claims"]) == 1
    assert report["flagged_claims"][0]["claim"] == "Made up claim"
