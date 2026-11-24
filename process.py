#!/usr/bin/env python3
"""
Process Tc_meas CSVs and plot Reactance vs Temperature.

- Scatter plot: red dots = warming, blue dots = cooling
- Finds steepest |dX/dT| using MEDIAN reactance at each setpoint (rounded T)
- Draws a vertical dashed line at the temperature where the steepest slope occurs
"""

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


# ======================================================================
#   HARDCODED INPUT PATHS
# ======================================================================
WARMING_CSV = Path(
    "/media/dmradio/Elements2/Cooldowns/Cooldown 39/Tc_meas/04-24-2026/output/Sample_A/2026-04-24_16-49-49/Warming.csv"
)

COOLING_CSV = Path(
    "/media/dmradio/Elements2/Cooldowns/Cooldown 39/Tc_meas/04-24-2026/output/Sample_A/2026-04-24_17-34-15/Cooling.csv"
)

CALIBRATION_CSV = Path(
    "/media/dmradio/Elements2/Cooldowns/Cooldown 39/Grafana_query/he4_plate_rox_calibration_1mK_bins_simple.csv"
)

def _read_tc_csv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)

    # Coerce numeric columns
    df["Reactance [Ω]"] = pd.to_numeric(df.get("Reactance [Ω]"), errors="coerce")
    df["Temperature [K]"] = pd.to_numeric(df.get("Temperature [K]"), errors="coerce")

    # Clean
    df = df.dropna(subset=["Reactance [Ω]", "Temperature [K]"])
    df = df[np.isfinite(df["Reactance [Ω]"]) & np.isfinite(df["Temperature [K]"])]

    return df

def apply_temperature_calibration(
    df: pd.DataFrame,
    calibration_csv: Path,
    temp_col: str = "Temperature [K]",
) -> pd.DataFrame:
    """
    Replace uncalibrated ROX temperatures with calibrated ROX temperatures
    using interpolation from the calibration CSV.

    Calibration CSV must have columns:
      T_uncalibrated_ROX_K
      T_calibrated_ROX_K
    """
    cal = pd.read_csv(calibration_csv)

    cal["T_uncalibrated_ROX_K"] = pd.to_numeric(
        cal["T_uncalibrated_ROX_K"], errors="coerce"
    )
    cal["T_calibrated_ROX_K"] = pd.to_numeric(
        cal["T_calibrated_ROX_K"], errors="coerce"
    )

    cal = cal.dropna(subset=["T_uncalibrated_ROX_K", "T_calibrated_ROX_K"])
    cal = cal.sort_values("T_uncalibrated_ROX_K")

    df = df.copy()

    T_uncal = df[temp_col].to_numpy(dtype=float)

    T_cal = np.interp(
        T_uncal,
        cal["T_uncalibrated_ROX_K"].to_numpy(dtype=float),
        cal["T_calibrated_ROX_K"].to_numpy(dtype=float),
    )

    df["Temperature_uncalibrated [K]"] = df[temp_col]
    df[temp_col] = T_cal

    return df

def compute_steepest_slope_one(
    df: pd.DataFrame | None,
    mode: str,
    t_round_decimals: int = 3,
):
    """
    Compute Tc-like point for one dataset only.

    Returns:
      Tc_est (float),
      slope (float),
      mode (str),
      segment (tuple) = (T1, X1, T2, X2)
    """
    if df is None or df.empty or df.shape[0] < 2:
        raise RuntimeError(f"Could not compute Tc for {mode}: not enough valid points.")

    df2 = df.copy()
    df2["T_round"] = df2["Temperature [K]"].round(t_round_decimals)

    # Median reactance per rounded temperature setpoint
    g = (
        df2.groupby(["T_round"], as_index=False)
        .agg(X_med=("Reactance [Ω]", "median"))
        .dropna()
    )

    if g.shape[0] < 2:
        raise RuntimeError(f"Could not compute Tc for {mode}: not enough setpoints.")

    g = g.sort_values("T_round")

    T = g["T_round"].to_numpy(dtype=float)
    X = g["X_med"].to_numpy(dtype=float)

    dT = np.diff(T)
    dX = np.diff(X)

    # Ignore zero/near-zero dT
    mask = np.abs(dT) > 1e-6
    if not np.any(mask):
        raise RuntimeError(f"Could not compute Tc for {mode}: all dT are zero.")

    slopes = dX[mask] / dT[mask]
    abs_slopes = np.abs(slopes)

    i_local = int(np.argmax(abs_slopes))
    valid_indices = np.where(mask)[0]
    i = int(valid_indices[i_local])

    T1, T2 = float(T[i]), float(T[i + 1])
    X1, X2 = float(X[i]), float(X[i + 1])
    slope = float(slopes[i_local])

    Tc = 0.5 * (T1 + T2)

    return Tc, slope, mode, (T1, X1, T2, X2)


def main():
    if not WARMING_CSV.exists():
        raise FileNotFoundError(f"Warming.csv not found: {WARMING_CSV}")
    if not COOLING_CSV.exists():
        raise FileNotFoundError(f"Cooling.csv not found: {COOLING_CSV}")

    T_MIN = 1.010
    T_MAX = 1.200
    X_MAX = 6.5

    warming_df = _read_tc_csv(WARMING_CSV)
    cooling_df = _read_tc_csv(COOLING_CSV)

    # Replace measured/un-calibrated ROX temperature with calibrated ROX temperature
    warming_df = apply_temperature_calibration(warming_df, CALIBRATION_CSV)
    cooling_df = apply_temperature_calibration(cooling_df, CALIBRATION_CSV)

    warming_df = warming_df[
        (warming_df["Temperature [K]"] >= T_MIN)
        & (warming_df["Temperature [K]"] <= T_MAX)
        & (warming_df["Reactance [Ω]"] <= X_MAX)
        ]

    cooling_df = cooling_df[
        (cooling_df["Temperature [K]"] >= T_MIN)
        & (cooling_df["Temperature [K]"] <= T_MAX)
        & (cooling_df["Reactance [Ω]"] <= X_MAX)
        ]

    # Find Tc-like points separately for warming and cooling
    Tc_warm, slope_warm, mode_warm, (T1_w, X1_w, T2_w, X2_w) = compute_steepest_slope_one(
        warming_df, "warming", t_round_decimals=3
    )

    Tc_cool, slope_cool, mode_cool, (T1_c, X1_c, T2_c, X2_c) = compute_steepest_slope_one(
        cooling_df, "cooling", t_round_decimals=3
    )

    # Plot
    plt.figure()

    if not warming_df.empty:
        plt.scatter(
            warming_df["Temperature [K]"],
            warming_df["Reactance [Ω]"],
            s=12,
            c="red",
            label="warming",
            alpha=0.8,
        )

    if not cooling_df.empty:
        plt.scatter(
            cooling_df["Temperature [K]"],
            cooling_df["Reactance [Ω]"],
            s=12,
            c="blue",
            label="cooling",
            alpha=0.8,
        )

    # dashed line at steepest slope temperature
    # dashed lines at warming and cooling Tc estimates
    plt.axvline(Tc_warm, linestyle="--", linewidth=1.5, color="red", label=f"Tc warming = {Tc_warm:.5f} K")
    plt.axvline(Tc_cool, linestyle="--", linewidth=1.5, color="blue", label=f"Tc cooling = {Tc_cool:.5f} K")

    plt.xlabel("Temperature [K]")
    plt.ylabel("Reactance [Ω]")
    plt.title("Reactance vs Temperature")

    # Annotate slope info
    txt = (
        f"warming Tc ≈ {Tc_warm:.5f} K\n"
        f"dX/dT ≈ {slope_warm:.3g} Ω/K, segment: {T1_w:.3f}K→{T2_w:.3f}K\n"
        f"cooling Tc ≈ {Tc_cool:.5f} K\n"
        f"dX/dT ≈ {slope_cool:.3g} Ω/K, segment: {T1_c:.3f}K→{T2_c:.3f}K"
    )
    plt.text(
        0.98, 0.02, txt,
        transform=plt.gca().transAxes,
        va="bottom",
        ha="right",
        fontsize=9,
        bbox=dict(boxstyle="round", alpha=0.15),
    )

    plt.grid(True, alpha=0.3)
    plt.legend()

    # Save outputs next to the warming file (you can change this if you want)
    out_base = WARMING_CSV.with_suffix("").as_posix()
    out_png = out_base + "_X_vs_T.png"
    out_pdf = out_base + "_X_vs_T.pdf"

    plt.savefig(out_png, dpi=200, bbox_inches="tight")
    plt.savefig(out_pdf, bbox_inches="tight")
    plt.show()

    print(f"Warming: {WARMING_CSV}")
    print(f"Cooling: {COOLING_CSV}")
    print(f"Saved:   {out_png}")
    print(f"Saved:   {out_pdf}")
    print(f"Warming Tc ≈ {Tc_warm:.6f} K, dX/dT={slope_warm:.6g} Ω/K")
    print(f"Cooling Tc ≈ {Tc_cool:.6f} K, dX/dT={slope_cool:.6g} Ω/K")
    print(f"Delta Tc = warming - cooling ≈ {Tc_warm - Tc_cool:.6f} K")

if __name__ == "__main__":
    main()
