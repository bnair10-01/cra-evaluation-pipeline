import pytest

@pytest.fixture(autouse=True)
def isolated_review_store(tmp_path,monkeypatch):
    """Tests never touch the project's real data/review.sqlite or reviews/decisions."""
    monkeypatch.setenv('CRA_REVIEW_DB',str(tmp_path/'review_test.sqlite'))
