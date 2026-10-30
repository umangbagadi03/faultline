import os
import tempfile

# Use a throwaway database for tests (must be set before faultline is imported).
os.environ["FAULTLINE_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["FAULTLINE_MODE"] = "rules"
