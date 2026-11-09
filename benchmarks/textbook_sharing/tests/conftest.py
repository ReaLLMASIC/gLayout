import os
import pytest
os.environ.setdefault("GLAYOUT_BACKEND", "gdsfactory")
from textbook_sharing import paths
paths.setup_imports()


def pytest_sessionstart(session):
    if not paths.CASES.exists():
        pytest.exit("the case folders are not unpacked: run `tar -xJf data/cases.tar.xz` in benchmarks/textbook_sharing", returncode=4)
