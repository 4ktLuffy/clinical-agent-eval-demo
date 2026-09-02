from eval.stats import agreement, bucket, cohens_kappa, prf, scored, wilson


def test_wilson_bounds():
    lo, hi = wilson(5, 5)
    assert 0.0 < lo < 1.0 and hi == 1.0
    assert wilson(0, 0) == (0.0, 1.0)
    lo, hi = wilson(50, 100)
    assert lo < 0.5 < hi


def test_wilson_narrows_with_n():
    narrow = wilson(80, 100)
    wide = wilson(8, 10)
    assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


def test_bucket_maps_to_three_levels():
    assert [bucket(x) for x in (0.0, 0.2, 0.4, 0.5, 0.7, 1.0)] == [0.0, 0.0, 0.5, 0.5, 1.0, 1.0]


def test_kappa_is_categorical_not_just_boolean():
    assert cohens_kappa([1.0, 0.5, 0.0], [1.0, 0.5, 0.0]) == 1.0
    assert cohens_kappa([1.0, 0.0, 1.0, 0.0], [1.0, 1.0, 0.0, 0.0]) == 0.0


def test_kappa_degenerate_cases_return_zero():
    """One rater using a single category everywhere leaves no room above chance."""
    assert cohens_kappa([1.0, 1.0, 1.0], [1.0, 1.0, 1.0]) == 0.0
    assert cohens_kappa([], []) == 0.0
    assert cohens_kappa([1.0, 0.0], [1.0]) == 0.0


def test_agreement_is_the_raw_rate():
    assert agreement([1, 0, 1], [1, 0, 0]) == 2 / 3


def test_prf_and_scored():
    assert prf(0, 0, 0) == (0.0, 0.0, 0.0)
    s = scored([True, True, False], [True, False, False])
    assert (s["tp"], s["fp"], s["fn"], s["tn"]) == (1, 1, 0, 1)
    assert s["recall"] == 1.0 and s["precision"] == 0.5
    assert s["precision_ci"][0] <= s["precision"] <= s["precision_ci"][1]
