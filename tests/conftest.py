import os
import pytest


@pytest.fixture(scope="session", autouse=True)
def test_env_bootstrap():
    os.environ.setdefault("OPENAI_API_KEY", "test-key")
    os.environ.setdefault("OPENAI_MODEL", "gpt-4o-mini")
    os.environ.setdefault("OPENAI_BASE_URL", "https://api.openai.com/v1")


@pytest.fixture(scope="session")
def integration_enabled() -> bool:
    return os.getenv("RUN_INTEGRATION_TESTS", "0") == "1"
