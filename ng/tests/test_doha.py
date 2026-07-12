"""Golden tests for the doha selection algorithm (must match legacy
app/dhamma/doha.php exactly)."""
import pytest

from gong_ng.doha import legacy_modular

# 10 Day: total_days=11, anapana_days=3
TEN_DAY = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8, 9: 9, 10: 10, 11: 11}

# STP: total_days=8, anapana_days=2 (also Teen)
STP = {1: 1, 2: 2, 3: 4, 4: 5, 5: 6, 6: 7, 7: 10, 8: 11}

# 20 Day: total_days=21, anapana_days=7 — metta_days=1 (total < 30)
TWENTY = {20: 10, 21: 11, 19: 3 + ((19 - 8) % 6) + 1}

# 30 Day: total_days=31, anapana_days=10 — metta_days=2
THIRTY = {29: 10, 30: 10, 31: 11}


@pytest.mark.parametrize("day,slot", sorted(TEN_DAY.items()))
def test_ten_day(day, slot):
    assert legacy_modular(day, 11, 3) == slot


@pytest.mark.parametrize("day,slot", sorted(STP.items()))
def test_stp(day, slot):
    assert legacy_modular(day, 8, 2) == slot


@pytest.mark.parametrize("day,slot", sorted(TWENTY.items()))
def test_twenty_day(day, slot):
    assert legacy_modular(day, 21, 7) == slot


@pytest.mark.parametrize("day,slot", sorted(THIRTY.items()))
def test_thirty_day_double_metta(day, slot):
    assert legacy_modular(day, 31, 10) == slot


def test_vipassana_cycle_wraps_4_to_9():
    # 45 Day (10A): total=46 anapana=10; days 11..16 -> 4..9, day 17 -> 4 again
    assert [legacy_modular(d, 46, 10) for d in range(11, 18)] == [4, 5, 6, 7, 8, 9, 4]
