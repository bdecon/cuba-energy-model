"""
Integrate renewables.ninja data into the model time series.

Replaces synthetic solar PV and wind profiles with real
satellite-derived data from renewables.ninja.

Solar PV parameters: lat=22, lon=-79.5, tilt=22, azimuth=180, loss=10%
Wind parameters: lat=22, lon=-79.5, Goldwind GW109/2500, hub_height=90m
Weather year: 2019
"""

import pandas as pd
import numpy as np

# Load existing time series (has demand and hydro)
ts = pd.read_csv("data/timeseries.csv")

# Load ninja data
solar = pd.read_csv("data/ninja_solar_raw.csv")
wind = pd.read_csv("data/ninja_wind_raw.csv")

print("Before (synthetic):")
print(f"  Solar CF: {ts.solar_pv.mean():.4f}")
print(f"  Wind CF:  {ts.wind.mean():.4f}")

# Replace solar and wind with real data
ts["solar_pv"] = solar["electricity"].values
ts["wind"] = wind["electricity"].values

print("\nAfter (renewables.ninja):")
print(f"  Solar CF: {ts.solar_pv.mean():.4f}")
print(f"  Wind CF:  {ts.wind.mean():.4f}")

# Show correlation between solar and wind (important for system balancing)
corr = np.corrcoef(ts["solar_pv"], ts["wind"])[0, 1]
print(f"\n  Solar-wind hourly correlation: {corr:.3f}")
print(f"  (Negative = complementary, good for system)")

# Save updated time series
ts.to_csv("data/timeseries.csv", index=False)
print("\nSaved updated timeseries.csv with real ninja data.")
