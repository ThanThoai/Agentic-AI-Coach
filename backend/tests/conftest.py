"""
Root conftest — shared fixtures for all tests (mock + live).
Load .env.test when present; fall back to .env.
"""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load test env file if it exists, otherwise fall back to regular .env
_test_env = Path(__file__).parent.parent / ".env.test"
_fallback_env = Path(__file__).parent.parent / ".env"
if _test_env.exists():
    load_dotenv(_test_env, override=True)
elif _fallback_env.exists():
    load_dotenv(_fallback_env, override=True)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "mock: fully offline test — no real API calls")
    config.addinivalue_line("markers", "live: calls real APIs — requires env keys to be set")
