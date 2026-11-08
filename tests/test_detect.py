from datetime import date, timedelta

from pytest import approx

from trend_radar.config import Settings
from trend_radar.detect import (
    TopList,
    baseline_from_history,
    baseline_from_top_lists,
    is_spike,
    lockstep,
    mobile_share,
    score,
)

DAY = date(2026, 11, 7)
S = Settings()


def test_exact_baseline_treats_missing_days_as_zero() -> None:
    history = {DAY - timedelta(days=i): 100 for i in range(1, 15)}  # only two weeks of data
    base = baseline_from_history(history, DAY, 28)
    assert base.days == 28
    assert base.median == 50  # 14 days at 100, 14 days at 0


def test_top_list_baseline_uses_cutoff_as_upper_bound() -> None:
    tops = {DAY - timedelta(days=i): TopList(DAY, {"A": 5_000, "B": 1_000}) for i in range(1, 29)}
    present = baseline_from_top_lists("A", DAY, tops, 28)
    absent = baseline_from_top_lists("C", DAY, tops, 28)
    assert present is not None and present.median == 5_000 and present.censored == 0
    assert absent is not None and absent.median == 1_000 and absent.censored == 28


def test_too_few_lists_gives_no_baseline() -> None:
    tops = {DAY - timedelta(days=1): TopList(DAY, {"A": 10})}
    assert baseline_from_top_lists("A", DAY, tops, 28) is None


def test_spike_rules() -> None:
    steady = {DAY - timedelta(days=i): 1_000 + (i % 5) * 20 for i in range(1, 29)}
    base = baseline_from_history(steady, DAY, 28)
    assert is_spike(score(9_000, base, S), S)
    assert not is_spike(score(1_200, base, S), S)  # normal noise
    small = baseline_from_history({DAY - timedelta(days=i): 100 for i in range(1, 29)}, DAY, 28)
    assert not is_spike(score(1_500, small, S), S)  # 15x, but under the 2,000-view minimum


def test_new_page_has_finite_scores() -> None:
    s = score(10_000, baseline_from_history({}, DAY, 28), S)
    assert s.ratio == 10_000 / S.median_floor
    assert s.z > 100


def test_mobile_share() -> None:
    desktop = TopList(DAY, {"Bot": 9_700, "Insan": 2_500, "Son": 800})
    assert mobile_share("Bot", 10_000, desktop) == approx(0.03)
    assert mobile_share("Insan", 10_000, desktop) == approx(0.75)
    assert mobile_share("Yok", 10_000, desktop) == approx(0.92)  # lower bound from the cutoff
    assert mobile_share("Yok", 500, desktop) is None  # cutoff above the views: no information
    assert mobile_share("Bot", 10_000, None) is None


def test_lockstep_finds_groups_with_equal_extra_views() -> None:
    excess = {
        "Tarih": 5_929,
        "Sanat": 5_890,
        "Bilim": 5_823,
        "Teknoloji": 5_942,
        "Maç": 48_000,
        "Oyuncu": 9_100,
        "Kulüp": 8_700,
    }
    assert lockstep(excess, 0.03, 4) == {"Tarih", "Sanat", "Bilim", "Teknoloji"}
    assert lockstep(excess, 0.03, 5) == set()
    assert lockstep({"A": 1_000, "B": 1_010, "C": 1_020}, 0.03, 4) == set()
