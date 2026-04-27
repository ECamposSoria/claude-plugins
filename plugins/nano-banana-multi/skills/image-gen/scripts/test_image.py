# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Pure-function tests. Run: `uv run pytest skills/image-gen/scripts/test_image.py -v`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest
from image import _openai_size


@pytest.mark.parametrize(
    "aspect,size,expected",
    [
        ("square",    "1K", "1024x1024"),
        ("landscape", "1K", "1536x1024"),
        ("portrait",  "1K", "1024x1536"),
        ("square",    "2K", "2048x2048"),
        ("landscape", "2K", "2048x1152"),
        ("portrait",  "2K", "1152x2048"),
        ("landscape", "4K", "3840x2160"),
        ("portrait",  "4K", "2160x3840"),
    ],
)
def test_openai_size_supported(aspect, size, expected):
    assert _openai_size(aspect, size) == expected


def test_openai_size_4k_square_falls_back_to_2k_square():
    # 4K square (3840x3840 = 14.7M px) exceeds the 8.29M px cap;
    # the helper must downgrade to 2K square rather than return an invalid size.
    assert _openai_size("square", "4K") == "2048x2048"
