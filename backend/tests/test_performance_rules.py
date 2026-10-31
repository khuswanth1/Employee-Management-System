from app.modules.performance import rules as r


def test_rating_scale_validation():
    ok = [(1, "Below"), (2, "Meets"), (3, "Exceeds")]
    assert r.validate_levels(ok) is None
    assert r.validate_levels([(1, "Only one")]) is not None
    assert r.validate_levels([(i, f"L{i}") for i in range(1, 12)]) is not None
    assert "own number" in r.validate_levels([(1, "a"), (1, "b")])
    assert r.validate_levels([(0, "a"), (1, "b")]) is not None
    assert r.validate_levels([(1, "a"), (2, "  ")]) is not None


def test_kpi_progress_is_clamped_and_safe():
    assert r.kpi_progress(50, 200) == 25
    assert r.kpi_progress(250, 200) == 100            # over-achievement does not exceed 100
    assert r.kpi_progress(-5, 200) == 0
    assert r.kpi_progress(None, 200) == 0 and r.kpi_progress(5, None) == 0 and r.kpi_progress(5, 0) == 0
    assert r.kpi_progress(1, 3) == 33


def test_weights_must_fit_within_one_hundred_percent():
    assert r.weights_fit([40, 30], 30) and not r.weights_fit([40, 30], 31)
    assert r.weights_fit([], 100) and r.weights_fit([100], 0)
    assert r.total_weight([10, 20]) == 30


def test_weighted_score():
    assert r.weighted_score([(50, 5), (50, 3)]) == 4.0
    assert r.weighted_score([(75, 4), (25, 2)]) == 3.5
    assert r.weighted_score([(0, 4), (0, 2)]) == 3.0              # no weights: simple average
    assert r.weighted_score([(50, None), (50, 4)]) == 4.0         # unrated goals are left out
    assert r.weighted_score([]) is None and r.weighted_score([(10, None)]) is None


def test_distribution_lists_every_level_and_average_handles_empty():
    assert r.distribution([3, 3, 4, 1], [1, 2, 3, 4, 5]) == {1: 1, 2: 0, 3: 2, 4: 1, 5: 0}
    assert r.average([3, 4, 4]) == 3.67 and r.average([]) is None
