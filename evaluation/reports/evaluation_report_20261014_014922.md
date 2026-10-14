# GeoRoute AI — Evaluation Report

**Run Timestamp:** 2026-10-13T20:19:19.827785+00:00  
**Overall Status:** `PASSED`  
**Git Commit:** `6e279c958b4a74f013e30dfac2b88862b5cbe00d`  
**Platform:** `Windows-11-10.0.26300-SP0`  
**PYORPS Engine:** `0.4.0`  

## 1. Scenario Execution Matrix

| Scenario ID | Name | Status | Key Diagnostics |
| :--- | :--- | :--- | :--- |
| `scenario_1_local_in_coverage_success` | Valid In-Coverage Corridor Optimization | **PASSED** | 3 routes evaluated; True valid |
| `scenario_2_out_of_coverage_rejection` | New Delhi Out-of-Coverage Rejection | **PASSED** | HTTP 422 (OUT_OF_COVERAGE) |
| `scenario_3_blocked_endpoint_no_snapping` | Impassable Obstacle Endpoint (No Snapping) | **PASSED** | HTTP 202 (N/A) |
| `scenario_4_synthetic_no_path_barrier` | Controlled Fixture: Infeasible Enclosed Barrier | **PASSED** | Barrier enforced: True |
| `scenario_5_job_cancellation` | Asynchronous Job Cancellation | **PASSED** | Cancelled job job_7168d14fcf6c |

## 2. Performance Measurements

- **Job Submission Latency:** 105.67 ms
- **Corridor Optimization Runtime:** 1609.51 ms
- **Out-of-Coverage Rejection Latency:** 20.57 ms

## 3. Engineering Disclaimer

> GeoRoute AI generates preliminary candidate corridors from available geospatial data and configurable cost assumptions. These outputs are not certified railway alignments, construction cost estimates, environmental clearances, or substitutes for professional engineering and surveying. Current precomputed coverage is limited to a local study area around Mandi, Himachal Pradesh; full Mandi-to-New Delhi corridor planning is not yet supported.
