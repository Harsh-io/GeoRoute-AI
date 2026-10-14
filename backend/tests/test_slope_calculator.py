"""Unit tests for topographic slope and gradient calculation."""

import math
import numpy as np
import pytest
from georoute.features.slope_calculator import SlopeCalculator


def test_slope_flat_plane():
    """Flat synthetic terrain must yield exactly 0.0 slope in interior cells."""
    dem = np.full((20, 20), fill_value=500.0, dtype=np.float32)
    calc = SlopeCalculator(cell_size_x=10.0, cell_size_y=10.0)
    result = calc.compute(dem)

    interior_deg = result.slope_degrees[1:-1, 1:-1]
    interior_pct = result.slope_percent[1:-1, 1:-1]

    assert np.allclose(interior_deg, 0.0, atol=1e-5)
    assert np.allclose(interior_pct, 0.0, atol=1e-5)
    assert result.summary_stats["min_degrees"] == 0.0
    assert result.summary_stats["max_degrees"] == 0.0


def test_slope_known_ten_percent_incline():
    """Planar surface with known 10% gradient along X axis must yield 10.0% slope."""
    # dx = 10m. Along X: z increases by 1m per 10m -> dz/dx = 0.10 (10% slope)
    # slope_percent = 10.0%, slope_degrees = arctan(0.10) * 180 / pi = 5.710593°
    H, W = 25, 25
    dem = np.zeros((H, W), dtype=np.float32)
    for col in range(W):
        dem[:, col] = col * 1.0  # +1m per 10m cell along columns (X)

    calc = SlopeCalculator(cell_size_x=10.0, cell_size_y=10.0)
    result = calc.compute(dem)

    interior_deg = result.slope_degrees[2:-2, 2:-2]
    interior_pct = result.slope_percent[2:-2, 2:-2]

    expected_deg = math.degrees(math.atan(0.10))  # ~5.71°
    expected_pct = 10.0

    assert np.allclose(interior_pct, expected_pct, atol=1e-3)
    assert np.allclose(interior_deg, expected_deg, atol=1e-3)


def test_slope_greater_than_one_hundred_percent_uncapped():
    """Slopes > 45 degrees (> 100% grade) must NOT be capped at 100%."""
    # 60 degree slope: rise/run = tan(60 deg) = sqrt(3) ~ 1.73205
    # slope_percent = 173.205%
    H, W = 15, 15
    target_rise_run = math.tan(math.radians(60.0))
    dem = np.zeros((H, W), dtype=np.float32)
    dx = 10.0
    for col in range(W):
        dem[:, col] = col * (target_rise_run * dx)

    calc = SlopeCalculator(cell_size_x=dx, cell_size_y=10.0)
    result = calc.compute(dem)

    interior_pct = result.slope_percent[2:-2, 2:-2]
    interior_deg = result.slope_degrees[2:-2, 2:-2]

    expected_pct = target_rise_run * 100.0  # ~173.2%
    assert np.allclose(interior_pct, expected_pct, atol=1e-2)
    assert np.allclose(interior_deg, 60.0, atol=1e-2)
    assert np.all(interior_pct > 100.0), "Steep slope must exceed 100% and not be capped!"


def test_slope_nodata_neighborhood_propagation():
    """Nodata elevation in a 3x3 window must produce nodata slope with no artifacts."""
    dem = np.full((10, 10), fill_value=100.0, dtype=np.float32)
    # Place nodata at (4, 4)
    dem[4, 4] = -9999.0

    calc = SlopeCalculator(cell_size_x=10.0, cell_size_y=10.0, nodata_val=-9999.0)
    result = calc.compute(dem)

    # Any cell where (4, 4) is in its 3x3 window (rows 3..5, cols 3..5) must be nodata
    for r in range(3, 6):
        for c in range(3, 6):
            assert result.slope_degrees[r, c] == -9999.0
            assert result.slope_percent[r, c] == -9999.0
            assert result.validity_mask[r, c] is False or result.validity_mask[r, c] == 0

    # Unaffected interior cells (e.g. at (1, 1)) must remain valid zero slope
    assert result.slope_degrees[1, 1] == 0.0
    assert result.validity_mask[1, 1] is True or result.validity_mask[1, 1] == 1


def test_slope_3d_input_and_summary_stats():
    """Accepts (1, H, W) shape and computes summary stats accurately."""
    dem = np.ones((1, 30, 30), dtype=np.float32) * 200.0
    # Add a 5m hill in center
    dem[0, 15, 15] = 205.0

    calc = SlopeCalculator(cell_size_x=10.0, cell_size_y=10.0)
    result = calc.compute(dem)

    assert result.slope_degrees.shape == (1, 30, 30)
    assert result.slope_percent.shape == (1, 30, 30)
    assert result.summary_stats["valid_pixels"] == 28 * 28
    assert result.summary_stats["max_degrees"] > 0.0


def test_slope_invalid_inputs():
    """Invalid inputs raise informative errors."""
    calc = SlopeCalculator()

    # Too small DEM
    with pytest.raises(ValueError, match="too small"):
        calc.compute(np.ones((2, 2)))

    # Non-positive cell size
    with pytest.raises(ValueError, match="strictly positive"):
        SlopeCalculator(cell_size_x=0.0)
