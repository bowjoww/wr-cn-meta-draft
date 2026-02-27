import pytest

from app.scoring import priority_score


def test_priority_score_formula():
    score = priority_score(winrate=0.5, pickrate=0.2, banrate=0.1)
    assert score == pytest.approx(0.21)


def test_priority_score_higher_banrate_increases_score():
    low = priority_score(winrate=0.51, pickrate=0.14, banrate=0.05)
    high = priority_score(winrate=0.51, pickrate=0.14, banrate=0.15)
    assert high > low
