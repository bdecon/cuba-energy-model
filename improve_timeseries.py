"""
Improve time series data for better Scenario 6 accuracy.

Four improvements:
0. TIMEZONE FIX: renewables.ninja data is in UTC; Cuba is UTC-5.
   Shift solar and wind profiles 5 hours earlier so they align with
   the local-time demand profile.
1. Eastern Cuba wind: Use real renewables.ninja data from 3 eastern
   sites (Gibara, Las Tunas, Camagüey) blended to represent
   geographically distributed wind generation.
2. Multi-site smoothing: Natural outcome of blending 3 real sites
   (reduces single-point intermittency).
3. Hydro capacity factors: Research-based monthly CFs (~20% annual avg).

Wind data sources (all renewables.ninja, 2019, Goldwind GW109/2500, 90m):
- Gibara (21.1N, -76.1W): CF 34.4% — existing wind farm site
- Las Tunas (21.3N, -76.0W): CF 37.5% — planned wind development
- Camagüey (21.8N, -77.9W): CF 31.5% — central-east coast

Hydro sources:
- IHA country profile (120 GWh/70MW = 19.6% CF in 2022)
- ONEI (64 GWh/64MW = 11.4% CF in 2019)
- Bautista et al. 2018 (Cauto River, MDPI Water) — precipitation seasonality
"""

import numpy as np
import pandas as pd

# ============================================================================
# Load data
# ============================================================================
ts = pd.read_csv("data/timeseries.csv")

# Load original ninja data (UTC) — solar from center Cuba, wind from 3 sites
ninja_solar = pd.read_csv("data/ninja_solar_raw.csv")
wind_gibara = pd.read_csv("data/ninja_wind_gibara_goldwind_raw.csv", comment="#")
wind_lastunas = pd.read_csv("data/ninja_wind_lastunas_raw.csv", comment="#")
wind_camaguey = pd.read_csv("data/ninja_wind_camaguey_raw.csv", comment="#")

print("=" * 60)
print("IMPROVING TIME SERIES FOR SCENARIO 6 ACCURACY")
print("=" * 60)

# ============================================================================
# 0. TIMEZONE FIX: Shift ninja data from UTC to Cuba local time (UTC-5)
# ============================================================================
print("\n--- TIMEZONE FIX (UTC → UTC-5) ---")
UTC_OFFSET = -5

solar_utc = ninja_solar["electricity"].values
solar_local = np.roll(solar_utc, UTC_OFFSET)

# Verify solar peak
hours_idx = pd.to_datetime(ninja_solar["time"]).dt.hour.values
solar_by_hour_utc = pd.Series(solar_utc).groupby(hours_idx).mean()
solar_by_hour_local = pd.Series(solar_local).groupby(hours_idx).mean()
print(f"  Solar peak hour: {solar_by_hour_utc.idxmax()} UTC → {solar_by_hour_local.idxmax()} local")

ts["solar_pv"] = solar_local

# ============================================================================
# 1 & 2. WIND: Real multi-site eastern Cuba data + timezone fix
# ============================================================================
print("\n--- WIND: MULTI-SITE EASTERN CUBA ---")

# Equal-weight blend of 3 eastern sites
wind_blend_utc = np.mean([
    wind_gibara["electricity"].values,
    wind_lastunas["electricity"].values,
    wind_camaguey["electricity"].values,
], axis=0)

# Shift UTC → local
wind_blend_local = np.roll(wind_blend_utc, UTC_OFFSET)

# Report
wind_by_hour_utc = pd.Series(wind_blend_utc).groupby(hours_idx).mean()
wind_by_hour_local = pd.Series(wind_blend_local).groupby(hours_idx).mean()
print(f"  Wind peak hour: {wind_by_hour_utc.idxmax()} UTC → {wind_by_hour_local.idxmax()} local")

print(f"  Individual site CFs:")
print(f"    Gibara:    {wind_gibara['electricity'].mean():.4f}")
print(f"    Las Tunas: {wind_lastunas['electricity'].mean():.4f}")
print(f"    Camagüey:  {wind_camaguey['electricity'].mean():.4f}")
print(f"  Blended CF:  {wind_blend_utc.mean():.4f}")
print(f"  (was {ts.wind.mean():.4f} from single central Cuba site)")

ts["wind"] = wind_blend_local

# ============================================================================
# 3. HYDRO: Research-based monthly capacity factors
# ============================================================================
print("\n--- HYDRO IMPROVEMENT ---")
old_hydro_cf = ts.hydro.mean()

HYDRO_MONTHLY_CF = {
    1: 0.13,   # Deep dry season
    2: 0.14,   # Dry season
    3: 0.13,   # Driest month
    4: 0.15,   # Late dry, pre-wet increase
    5: 0.25,   # Wet season onset
    6: 0.28,   # Full wet season
    7: 0.22,   # Mid-wet (veranillo dip)
    8: 0.23,   # Wet season
    9: 0.29,   # Peak wet, highest river flows
    10: 0.29,  # Peak wet, highest river flows
    11: 0.17,  # Transition to dry
    12: 0.13,  # Dry season begins
}

timestamps = pd.to_datetime(ts["timestamp"])
months = timestamps.dt.month
ts["hydro"] = np.array([HYDRO_MONTHLY_CF[m] for m in months])

print(f"  CF: {old_hydro_cf:.3f} → {ts.hydro.mean():.3f}")
print(f"  Generation (60 MW): {old_hydro_cf*60*8760/1e3:.0f} → {ts.hydro.mean()*60*8760/1e3:.0f} GWh/yr")

# ============================================================================
# SUMMARY
# ============================================================================
print("\n--- SUMMARY ---")
corr = np.corrcoef(ts["solar_pv"], ts["wind"])[0, 1]
print(f"Solar-wind correlation: {corr:.3f}")
print(f"Solar CF: {ts.solar_pv.mean():.4f}")
print(f"Wind CF:  {ts.wind.mean():.4f}")
print(f"Hydro CF: {ts.hydro.mean():.4f}")
print(f"Demand:   {ts.demand_mwh.sum()/1e6:.1f} TWh")

print("\nHourly average CFs (local time):")
print(f"  {'Hour':>4}  {'Solar':>6}  {'Wind':>6}  {'Combined':>8}")
hour_of_day = timestamps.dt.hour
for h in range(24):
    mask = hour_of_day == h
    s = ts.loc[mask, "solar_pv"].mean()
    w = ts.loc[mask, "wind"].mean()
    print(f"  {h:4d}  {s:6.3f}  {w:6.3f}  {s+w:8.3f}")

# Night vs day wind
night_hours = [18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5]
day_hours = [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17]
night_wind = ts.loc[hour_of_day.isin(night_hours), "wind"].mean()
day_wind = ts.loc[hour_of_day.isin(day_hours), "wind"].mean()
print(f"\n  Wind night/day ratio: {night_wind/day_wind:.2f} "
      f"(night={night_wind:.3f}, day={day_wind:.3f})")

# Save
ts.to_csv("data/timeseries.csv", index=False)
print(f"\nSaved improved timeseries.csv")
print("=" * 60)
