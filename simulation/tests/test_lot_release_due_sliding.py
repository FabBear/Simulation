from fab_env import calc_minutes


def test_sliding_due_formula_option_a():
    base_due = calc_minutes("2018-02-21 15:27:08")
    interval = 51.69
    dues = [base_due + k * interval for k in range(3)]
    assert round(dues[1] - dues[0], 2) == interval
    assert round(dues[2] - dues[1], 2) == interval
