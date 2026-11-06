import os
import tempfile

# Must be set before agentlog is imported: paths are resolved at import time.
# Keeps tests away from the real log.
os.environ["AGENTLOG_HOME"] = tempfile.mkdtemp(prefix="agentlog-test-")
