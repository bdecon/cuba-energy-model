"""
Improved electricity demand profile for Cuba 2030.

Based on visual analysis of CubaLinda model figures (Luukkanen et al., 2022):
- Figure 8: January demand shows nighttime ~2000 MW, evening peak ~5000+ MW
- Figure 29: Load duration curve shows peak ~7000 MW, baseload ~2000 MW
- The CURE paper states peak loads often reach 3 GW (current system)
  and projects 27 TWh annual demand for 2030

Key characteristics of Cuban electricity demand:
- Very pronounced evening peak (19:00-21:00) driven by residential use
- Relatively low nighttime demand (limited industrial baseload)
- Higher summer demand (cooling loads)
- Weekend reduction ~15-20%
- 24 daily profiles: 12 months × weekday/weekend
"""

import numpy as np
import pandas as pd

np.random.seed(42)

# Target: 27 TWh annual, peak ~4500 MW based on paper's statement
# that "daily peak loads often reaching 3 GW" currently with ~20 TWh
# Scaling: 3 GW * (27/20) ≈ 4 GW, with growth margin → ~4500 MW peak

ANNUAL_DEMAND_MWH = 27_000_000
hours = pd.date_range("2030-01-01", periods=8760, freq="h")


def cuban_daily_profile(month, is_weekend):
    """
    Generate a 24-hour normalized load profile for Cuba.

    Based on CubaLinda Figure 8 demand patterns and typical Caribbean
    island load curves: low overnight, gradual morning rise, midday plateau,
    sharp evening peak from lighting/cooking/TV.
    """
    # Base profile: tropical island with strong evening peak
    # Values are relative to the evening peak (=1.0)
    if is_weekend:
        profile = np.array([
            0.38,  # 00:00
            0.35,  # 01:00
            0.33,  # 02:00
            0.32,  # 03:00
            0.32,  # 04:00
            0.33,  # 05:00
            0.36,  # 06:00
            0.42,  # 07:00
            0.50,  # 08:00
            0.56,  # 09:00
            0.62,  # 10:00
            0.66,  # 11:00
            0.68,  # 12:00
            0.65,  # 13:00
            0.62,  # 14:00
            0.60,  # 15:00
            0.60,  # 16:00
            0.65,  # 17:00
            0.78,  # 18:00
            0.92,  # 19:00 - evening ramp
            1.00,  # 20:00 - PEAK
            0.95,  # 21:00
            0.78,  # 22:00
            0.55,  # 23:00
        ])
    else:
        # Weekday: higher daytime (commercial/industrial) + evening peak
        profile = np.array([
            0.40,  # 00:00
            0.37,  # 01:00
            0.35,  # 02:00
            0.34,  # 03:00
            0.34,  # 04:00
            0.36,  # 05:00
            0.42,  # 06:00
            0.55,  # 07:00
            0.65,  # 08:00
            0.72,  # 09:00
            0.76,  # 10:00
            0.78,  # 11:00
            0.76,  # 12:00 - slight lunch dip
            0.72,  # 13:00
            0.70,  # 14:00
            0.68,  # 15:00
            0.68,  # 16:00
            0.72,  # 17:00
            0.82,  # 18:00
            0.95,  # 19:00 - evening ramp
            1.00,  # 20:00 - PEAK
            0.95,  # 21:00
            0.80,  # 22:00
            0.58,  # 23:00
        ])

    # Seasonal modulation: summer months have higher midday (cooling)
    # and slightly higher overall, winter has sharper evening-to-day ratio
    summer_months = [5, 6, 7, 8, 9, 10]
    if month in summer_months:
        # Increase midday demand (AC load) by ~5%
        for h in range(10, 17):
            profile[h] *= 1.05

    return profile


def generate_demand():
    """Generate 8760-hour demand profile for Cuba 2030."""
    n = len(hours)
    demand = np.zeros(n)

    # Monthly scaling factors (relative demand level)
    # Cuba: higher in summer (cooling), lower in winter
    monthly_scale = {
        1: 0.90, 2: 0.88, 3: 0.90, 4: 0.95,
        5: 1.02, 6: 1.08, 7: 1.12, 8: 1.12,
        9: 1.08, 10: 1.02, 11: 0.95, 12: 0.92,
    }

    for i in range(n):
        dt = hours[i]
        month = dt.month
        hour = dt.hour
        is_weekend = dt.dayofweek >= 5

        profile = cuban_daily_profile(month, is_weekend)
        demand[i] = profile[hour] * monthly_scale[month]

    # Add small random variation (weather-driven demand fluctuations)
    noise = np.random.normal(0, 0.02, n)
    # Smooth noise over a few hours
    kernel = np.ones(3) / 3
    noise = np.convolve(noise, kernel, mode="same")
    demand *= (1 + noise)

    # Scale to target annual demand
    current_total = demand.sum()
    demand *= ANNUAL_DEMAND_MWH / current_total

    return demand


if __name__ == "__main__":
    demand = generate_demand()

    print("Cuba 2030 Improved Demand Profile")
    print(f"  Annual demand: {demand.sum()/1e6:.1f} TWh")
    print(f"  Peak demand:   {demand.max():.0f} MW")
    print(f"  Min demand:    {demand.min():.0f} MW")
    print(f"  Avg demand:    {demand.mean():.0f} MW")
    print(f"  Peak/min ratio: {demand.max()/demand.min():.2f}")
    print(f"  Load factor:   {demand.mean()/demand.max():.3f}")

    # Monthly breakdown
    ts_df = pd.DataFrame({"demand": demand}, index=hours)
    monthly = ts_df.resample("ME").agg(["sum", "max", "min"])
    monthly.columns = ["total_gwh", "peak_mw", "min_mw"]
    monthly["total_gwh"] /= 1000
    print("\n  Monthly summary:")
    print(f"  {'Month':<10} {'Total GWh':>10} {'Peak MW':>10} {'Min MW':>10}")
    for i, (idx, row) in enumerate(monthly.iterrows()):
        print(f"  {idx.strftime('%B'):<10} {row.total_gwh:>10.0f} {row.peak_mw:>10.0f} {row.min_mw:>10.0f}")

    # Update timeseries.csv
    ts = pd.read_csv("data/timeseries.csv")
    print(f"\n  Old demand - peak: {ts.demand_mwh.max():.0f}, min: {ts.demand_mwh.min():.0f}, ratio: {ts.demand_mwh.max()/ts.demand_mwh.min():.2f}")

    ts["demand_mwh"] = demand
    ts.to_csv("data/timeseries.csv", index=False)
    print(f"  New demand - peak: {demand.max():.0f}, min: {demand.min():.0f}, ratio: {demand.max()/demand.min():.2f}")
    print("\n  Saved to data/timeseries.csv")
