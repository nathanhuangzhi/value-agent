import pytest

from app import db


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path):
    """Every test gets its own app.db so accounts/watchlists never leak."""
    db.use_path(tmp_path / "app.db")
    yield
    db.use_path(db.APP_DB)
