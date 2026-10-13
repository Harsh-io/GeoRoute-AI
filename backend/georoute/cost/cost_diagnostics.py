"""Diagnostic visualization generator for multi-objective cost surfaces.

Generates multi-panel comparative visualizations:
- Distance Cost Surface
- Estimated Construction Difficulty Surface
- Environmental Impact Proxy Surface
- Hard Constraint and Validity Masks

Clearly distinguishes low cost, high cost, blocked cells, and unknown data.
Never displays nodata or blocked areas as low-cost traversable terrain.
"""

import logging
from pathlib import Path
from typing import Optional, Tuple, Union
import numpy as np

logger = logging.getLogger("georoute.cost.diagnostics")


class CostDiagnosticsVisualizer:
    """Produces diagnostic comparison figures for cost surfaces and constraint masks."""

    def __init__(self, blocked_cell_cost: float = -9999.0):
        self.blocked_cell_cost = float(blocked_cell_cost)

    def plot_cost_surfaces_comparison(
        self,
        distance_cost: np.ndarray,
        construction_cost: np.ndarray,
        environmental_cost: np.ndarray,
        hard_constraint_mask: np.ndarray,
        output_path: Union[str, Path],
        region_name: str = "mandi_terminal_5x5km",
    ) -> Path:
        """Plots the three cost surfaces side-by-side with masked blocked cells.

        Args:
            distance_cost: 2D Float32 array of distance traversal cost.
            construction_cost: 2D Float32 array of construction difficulty cost.
            environmental_cost: 2D Float32 array of environmental proxy cost.
            hard_constraint_mask: 2D uint8 mask (1=blocked).
            output_path: Destination path for the saved image file.
            region_name: Study area label.

        Returns:
            Path to the saved image file.
        """
        import matplotlib
        matplotlib.use("Agg")  # Non-interactive backend
        import matplotlib.pyplot as plt
        from matplotlib.colors import Normalize

        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)

        # Mask blocked / nodata cells
        def make_masked(arr: np.ndarray) -> np.ma.MaskedArray:
            blocked = (arr == self.blocked_cell_cost) | (hard_constraint_mask == 1) | np.isnan(arr)
            return np.ma.masked_where(blocked, arr)

        dist_m = make_masked(distance_cost)
        const_m = make_masked(construction_cost)
        env_m = make_masked(environmental_cost)

        fig, axes = plt.subplots(1, 3, figsize=(18, 6), constrained_layout=True)
        fig.suptitle(
            f"GeoRoute AI — Multi-Objective Cost Surfaces Comparison [{region_name}]\n"
            f"(Blocked / Nodata Cells Masked in Dark Gray)",
            fontsize=14,
            fontweight="bold",
            y=1.05,
        )

        panels = [
            (
                axes[0],
                dist_m,
                "Distance Traversal Cost",
                "viridis",
                "Traversal Cost (m / 10m cell)",
                "Minimizes physical distance",
            ),
            (
                axes[1],
                const_m,
                "Estimated Construction Difficulty",
                "YlOrRd",
                "Difficulty Cost (Score × 10m)",
                "Penalizes steep slopes, built-up & water",
            ),
            (
                axes[2],
                env_m,
                "Environmental-Impact Proxy",
                "YlGn",
                "Sensitivity Cost (Proxy × 10m)",
                "Penalizes canopy, wetlands & habitat",
            ),
        ]

        for ax, data, title, cmap, cbar_label, subtitle in panels:
            # Set background color for blocked / nodata cells
            ax.set_facecolor("#222222")

            im = ax.imshow(data, cmap=cmap, interpolation="nearest")
            ax.set_title(f"{title}\n({subtitle})", fontsize=11, pad=8)
            ax.set_xlabel("Pixel Column (Easting 10m)")
            ax.set_ylabel("Pixel Row (Northing 10m)")

            cbar = fig.colorbar(im, ax=ax, orientation="horizontal", pad=0.04, fraction=0.06)
            cbar.set_label(cbar_label, fontsize=9)

        plt.savefig(out_file, dpi=200, bbox_inches="tight")
        plt.close(fig)

        logger.info(f"Saved cost surfaces diagnostic plot to: {out_file}")
        return out_file
