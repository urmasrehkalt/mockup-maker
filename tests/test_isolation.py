import os

from app import config

# Settings a developer's .env may hold that must never reach a test.
LOCAL_SETTINGS = ("TRACKER_URL", "TRACKER_PUBLIC_URL", "TRACKER_POINTS", "TRACKER_TIMEOUT",
                  "CODEX_BIN", "CODEX_HOME", "AI_MODEL", "AI_REASONING", "AI_TIMEOUT", "PORT")


def test_tests_use_the_stand_in_ai_and_no_tracker():
    # Regression (#24): with a developer .env (AI_PROVIDER=codex, TRACKER_URL=...) the suite
    # used to read those values, so a test could reach the real Codex CLI or a real tracker.
    assert config.ai_provider() == "mock"
    assert config.tracker_url() is None
    assert config.tracker_public_url() is None
    leaked = [name for name in LOCAL_SETTINGS if name in os.environ]
    assert leaked == []
