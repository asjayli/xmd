from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def tcp_pdf(fixtures_dir) -> Path:
    return fixtures_dir / "tcp-handshake.note.pdf"


@pytest.fixture
def blinko_pdf(fixtures_dir) -> Path:
    return fixtures_dir / "blinko.note.pdf"


@pytest.fixture
def finance_pdf(fixtures_dir) -> Path:
    return fixtures_dir / "finance.note.pdf"
