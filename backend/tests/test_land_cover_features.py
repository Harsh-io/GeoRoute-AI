"""Unit tests for LandCoverClassifier and optical NDVI validation."""

import numpy as np
import pytest

from georoute.features.land_cover_classifier import LandCoverClassifier, ESA_WORLDCOVER_CLASSES


@pytest.fixture
def classifier():
    return LandCoverClassifier(target_shape=(10, 10), cell_resolution=(10.0, 10.0))


def test_extract_class_masks(classifier):
    lc = np.full((10, 10), 40, dtype=np.uint8)  # Cropland
    lc[0:2, 0:2] = 10  # Tree cover (4 pixels)
    lc[5, 5] = 80      # Water (1 pixel)
    lc[8, 8] = 90      # Herbaceous wetland (1 pixel)
    lc[9, 9] = 95      # Mangroves (1 pixel)

    masks = classifier.extract_class_masks(lc)

    assert "forest_mask" in masks
    assert "cropland_mask" in masks
    assert "water_mask" in masks
    assert "wetland_mask" in masks

    assert masks["forest_mask"].sum() == 4
    assert masks["forest_mask"][0, 0] == 1
    assert masks["water_mask"].sum() == 1
    assert masks["water_mask"][5, 5] == 1
    assert masks["wetland_mask"].sum() == 2  # Both 90 and 95
    assert masks["cropland_mask"].sum() == (100 - 4 - 1 - 2)


def test_compute_summary(classifier):
    lc = np.full((10, 10), 10, dtype=np.uint8)  # 100 Tree cover pixels
    lc[0, 0] = 0  # 1 nodata pixel

    summary = classifier.compute_summary(lc, nodata=0)

    assert summary["total_pixels"] == 100
    assert summary["nodata_pixels"] == 1
    assert summary["valid_pixels"] == 99
    # 99 Tree cover pixels -> 100% of valid
    tree_info = summary["classes"]["10"]
    assert tree_info["pixel_count"] == 99
    assert tree_info["percentage"] == 100.0
    # 99 pixels * 100 m2 = 9,900 m2 = 0.0099 km2
    assert tree_info["area_km2"] == 0.0099


def test_get_class_mapping(classifier):
    mapping = classifier.get_class_mapping()
    assert "legend" in mapping
    assert "10" in mapping["legend"]
    assert mapping["legend"]["10"]["name"] == "Tree cover"
    assert "part3_implication" in mapping["legend"]["10"]


def test_compute_ndvi():
    # 4 bands: B04 (Red), B03 (Green), B02 (Blue), B08 (NIR)
    optical = np.zeros((4, 2, 2), dtype=np.float32)

    # Pixel (0, 0): High NIR (0.8), Low Red (0.1) -> NDVI = (0.8 - 0.1) / (0.8 + 0.1) = 0.7 / 0.9 ≈ 0.7778
    optical[0, 0, 0] = 0.1  # Red
    optical[3, 0, 0] = 0.8  # NIR

    # Pixel (0, 1): Low NIR (0.05), High Red (0.2) -> NDVI = (0.05 - 0.2) / (0.05 + 0.2) = -0.15 / 0.25 = -0.6
    optical[0, 0, 1] = 0.2  # Red
    optical[3, 0, 1] = 0.05 # NIR

    # Pixel (1, 1): Zero denominator -> Nodata
    optical[0, 1, 1] = 0.0
    optical[3, 1, 1] = 0.0

    ndvi = LandCoverClassifier.compute_ndvi(optical, red_band_idx=0, nir_band_idx=3, nodata_val=-9999.0)

    assert ndvi.shape == (2, 2)
    assert pytest.approx(ndvi[0, 0], abs=1e-3) == 0.7778
    assert pytest.approx(ndvi[0, 1], abs=1e-3) == -0.6
    assert ndvi[1, 1] == -9999.0


def test_validate_with_optical(classifier):
    # 10x10 grid: left half is forest (10), right half is water (80)
    lc = np.full((10, 10), 10, dtype=np.uint8)
    lc[:, 5:] = 80

    optical = np.zeros((4, 10, 10), dtype=np.float32)
    # Forest pixels: high NIR (0.8), low Red (0.1)
    optical[0, :, :5] = 0.1
    optical[3, :, :5] = 0.8
    # Water pixels: low NIR (0.05), higher Red (0.2)
    optical[0, :, 5:] = 0.2
    optical[3, :, 5:] = 0.05

    results = classifier.validate_with_optical(lc, optical)
    assert results["plausibility_passed"] is True
    assert results["forest_ndvi"]["mean"] > 0.7
    assert results["water_ndvi"]["mean"] < 0.0
