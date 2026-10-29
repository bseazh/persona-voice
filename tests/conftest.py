import os
import sys

os.environ["DATABASE_PATH"] = "/tmp/persona_voice_test.db"
os.environ["MOCK_STEP_DELAY_SECONDS"] = "0.01"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "api"))

