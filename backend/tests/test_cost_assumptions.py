"""Unit tests for CostAssumptions configuration model and validation."""

from pathlib import Path
import pytest
from pydantic import ValidationError

from georoute.cost.cost_assumptions import CostAssumptions


def test_default_cost_assumptions():
    assumptions = CostAssumptions()
    assert assumptions.model_version == "1.0.0"
    assert assumptions.distance.base_cell_distance_m == 10.0
    assert assumptions.slope.slope_reference == 20.0
    assert assumptions.slope.power == 2.0
    assert assumptions.landcover.class_penalties[10] == 2.5
    assert assumptions.environmental.protected_area_policy == "HARD_EXCLUSION"
    assert assumptions.constraints.treat_nodata_as_blocked is True


def test_load_cost_assumptions_from_yaml():
    yaml_path = Path("config/cost_assumptions.yaml")
    if not yaml_path.exists():
        pytest.skip("config/cost_assumptions.yaml does not exist")

    assumptions = CostAssumptions.from_yaml(yaml_path)
    assert assumptions.model_version == "1.0.0"
    assert assumptions.slope.slope_source == "slope_percent"
    assert assumptions.obstacles.water_crossing_penalty == 5.0


def test_json_roundtrip(tmp_path):
    assumptions = CostAssumptions()
    json_path = tmp_path / "test_assumptions.json"
    assumptions.to_json(json_path)

    assert json_path.exists()
    import json
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    loaded = CostAssumptions(**data)
    assert loaded.distance.base_cell_distance_m == assumptions.distance.base_cell_distance_m
    assert loaded.slope.power == assumptions.slope.power


def test_validation_errors():
    # Negative slope reference should fail
    with pytest.raises(ValidationError):
        CostAssumptions(slope={"slope_reference": -10.0})

    # Invalid slope source should fail
    with pytest.raises(ValidationError):
        CostAssumptions(slope={"slope_source": "invalid_source"})

    # Invalid protected area policy should fail
    with pytest.raises(ValidationError):
        CostAssumptions(environmental={"protected_area_policy": "INVALID_POLICY"})

    # Negative land cover penalty should fail
    with pytest.raises(ValidationError):
        CostAssumptions(landcover={"class_penalties": {10: -2.0}})
