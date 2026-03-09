import os
import pytest

@pytest.fixture
def integration_enabled():

    return os.environ.get("RUN_INTEGRATION_TESTS") == "1"