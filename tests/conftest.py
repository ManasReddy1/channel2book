"""Shared test fixtures."""

import json
import os
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from channel2book.config import Config
from channel2book.db import Database


@pytest.fixture
def tmp_dir():
    """Provide a temporary directory for test outputs."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest_asyncio.fixture
async def db(tmp_dir):
    """Provide a fresh in-memory-like test database."""
    db_path = tmp_dir / "test.db"
    database = Database(db_path)
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def config(tmp_dir):
    """Provide a test config."""
    return Config(
        channel_url="https://www.youtube.com/@testchannel",
        output=type(Config().output)(output_dir=str(tmp_dir)),
    )


@pytest.fixture
def fixtures_dir():
    """Path to test fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_channel_data():
    """Sample yt-dlp channel output."""
    return {
        "id": "test_channel_123",
        "channel_id": "UC_test123",
        "channel": "Test Channel",
        "uploader": "Test Channel",
        "channel_url": "https://www.youtube.com/@testchannel",
    }


@pytest.fixture
def sample_video_data():
    """Sample yt-dlp video output."""
    return {
        "id": "dQw4w9WgXcQ",
        "title": "Test Video Title",
        "description": "A test video description",
        "duration": 300,
        "upload_date": "20240101",
    }


@pytest.fixture
def sample_transcript_text():
    """Sample transcript text for testing."""
    return (
        "Welcome to this tutorial on machine learning. "
        "Today we'll cover the basics of neural networks. "
        "A neural network is a computational model inspired by the brain. "
        "It consists of layers of interconnected nodes called neurons. "
        "Each connection has a weight that gets adjusted during training. "
        "The process of adjusting weights is called backpropagation. "
        "Let's look at a simple example using Python. "
        "First, we import the necessary libraries. "
        "Then we define our model architecture. "
        "Finally, we train the model on our dataset."
    )
