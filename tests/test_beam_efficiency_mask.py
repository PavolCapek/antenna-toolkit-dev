import numpy as np

from beamwidth_xlsx import build_mainlobe_mask


def test_mainlobe_mask_ignores_shallow_minimum_inside_flat_main_beam():
    thetas = np.arange(0.0, 181.0, 1.0)
    rel_db = np.full(thetas.shape, -35.0, dtype=float)

    rel_db[:8] = -0.03
    rel_db[8] = 0.0
    rel_db[9] = -0.05
    rel_db[10] = -0.01
    rel_db[11:59] = np.linspace(-0.2, -18.0, 48)
    rel_db[59] = -24.0
    rel_db[60] = -30.0
    rel_db[61] = -24.0
    rel_db[62:] = -30.0

    power = np.tile(10.0 ** (rel_db / 10.0), (2, 1))

    mask, bounds = build_mainlobe_mask(power, thetas, smooth_w=1, theta_window_deg=8.0)

    assert bounds[0] == (0, 0.0, 60.0)
    assert mask[0, 9] == 1.0
    assert mask[0, 60] == 1.0
    assert mask[0, 61] == 0.0
