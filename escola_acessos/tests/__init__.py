import os
import tempfile

# Os testes nunca tocam em data/: usam sempre uma pasta temporária.
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="escola_tests_"))
