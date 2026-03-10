"""
Generate approximate time series for Cuba energy system model.

Creates hourly profiles (8760 values) for:
- Solar PV (based on renewables.ninja parameters: 22° tilt, 180° azimuth, 10% losses)
- Wind (based on Goldwind GW109/2500, 90m hub height)
- Hydropower (monthly constant generation)
- Electricity demand (seasonal/daily patterns)

Since we cannot access renewables.ninja directly, we create synthetic but realistic
profiles based on Cuba's geography (~22°N latitude, Caribbean climate).
"""

import numpy as np
import pandas as pd

np.random.seed(42)

# Create hourly datetime index for one year
hours = pd.date_range("2030-01-01", periods=8760, freq="h")


def generate_solar_pv(hours):
    """
    Generate normalized solar PV capacity factor time series.
    Cuba ~22°N, tilt 22°, azimuth 180° (south-facing), 10% system losses.
    Expected capacity factor ~18-20% annually.
    """
    n = len(hours)
    day_of_year = hours.dayofyear.values
    hour_of_day = hours.hour.values + hours.minute.values / 60.0

    # Solar declination angle (degrees)
    declination = 23.45 * np.sin(np.radians(360 / 365 * (day_of_year - 81)))

    # Latitude of Cuba (center)
    lat = 22.0  # degrees

    # Hour angle (degrees) - solar noon at ~12:30 local
    hour_angle = 15.0 * (hour_of_day - 12.5)

    # Solar altitude angle
    sin_altitude = (
        np.sin(np.radians(lat)) * np.sin(np.radians(declination))
        + np.cos(np.radians(lat))
        * np.cos(np.radians(declination))
        * np.cos(np.radians(hour_angle))
    )
    sin_altitude = np.clip(sin_altitude, 0, None)

    # Angle of incidence on tilted surface (simplified for south-facing tilt=lat)
    tilt = 22.0
    cos_incidence = (
        np.sin(np.radians(declination)) * np.sin(np.radians(lat - tilt))
        + np.cos(np.radians(declination))
        * np.cos(np.radians(lat - tilt))
        * np.cos(np.radians(hour_angle))
    )
    cos_incidence = np.clip(cos_incidence, 0, None)

    # Clear sky irradiance on tilted surface (normalized)
    # Add atmospheric effects
    clearness = np.where(sin_altitude > 0.05, sin_altitude ** 0.3, 0)
    pv_output = cos_incidence * clearness

    # Normalize to peak = 1
    if pv_output.max() > 0:
        pv_output = pv_output / pv_output.max()

    # Apply system losses (10%)
    pv_output *= 0.90

    # Add cloud cover variability (Cuba: drier in winter, wetter in summer)
    cloud_factor = np.ones(n)
    for i in range(n):
        month = hours[i].month
        # Wet season: May-October, Dry season: Nov-April
        if month in [5, 6, 7, 8, 9, 10]:
            cloud_factor[i] = np.random.uniform(0.65, 1.0)
        else:
            cloud_factor[i] = np.random.uniform(0.80, 1.0)

    # Smooth cloud factor slightly (clouds persist for hours)
    kernel_size = 3
    cloud_factor = np.convolve(
        cloud_factor, np.ones(kernel_size) / kernel_size, mode="same"
    )

    pv_output *= cloud_factor

    # Normalize so annual capacity factor ~ 18-20%
    current_cf = pv_output.mean()
    target_cf = 0.19
    if current_cf > 0:
        pv_output *= target_cf / current_cf

    pv_output = np.clip(pv_output, 0, 1)

    return pv_output


def generate_wind(hours):
    """
    Generate normalized wind capacity factor time series.
    Based on Goldwind GW109/2500 (2.5 MW, 109m rotor, 90m hub height).
    Cuba has good wind resources (trade winds), expected CF ~33-35%.
    """
    n = len(hours)
    day_of_year = hours.dayofyear.values
    hour_of_day = hours.hour.values

    # Base wind speed pattern (Cuba: trade winds, stronger in winter/spring)
    # Seasonal component
    seasonal = 1.0 + 0.2 * np.cos(2 * np.pi * (day_of_year - 45) / 365)

    # Diurnal component (slightly stronger in afternoon)
    diurnal = 1.0 + 0.1 * np.cos(2 * np.pi * (hour_of_day - 15) / 24)

    # Base wind speed at hub height (m/s) - Cuba avg ~6-7 m/s at 90m
    base_speed = 6.5 * seasonal * diurnal

    # Add turbulence / weather variability
    # Use correlated noise (weather fronts last several hours)
    noise = np.random.normal(0, 1, n)
    # Auto-correlate with ~6 hour persistence
    alpha = 0.85
    corr_noise = np.zeros(n)
    corr_noise[0] = noise[0]
    for i in range(1, n):
        corr_noise[i] = alpha * corr_noise[i - 1] + np.sqrt(1 - alpha**2) * noise[i]

    wind_speed = base_speed + 2.5 * corr_noise
    wind_speed = np.clip(wind_speed, 0, 25)

    # Wind turbine power curve (GW109/2500 approximation)
    # Cut-in: 3 m/s, Rated: 10.3 m/s, Cut-out: 25 m/s
    cf = np.zeros(n)
    for i in range(n):
        v = wind_speed[i]
        if v < 3:
            cf[i] = 0
        elif v < 10.3:
            # Cubic relationship between cut-in and rated
            cf[i] = ((v - 3) / (10.3 - 3)) ** 3
        elif v < 22:
            cf[i] = 1.0
        elif v < 25:
            cf[i] = 1.0 - (v - 22) / 3
        else:
            cf[i] = 0

    # Scale to realistic annual CF (~34%) based on renewables.ninja for Cuba
    current_cf = cf.mean()
    target_cf = 0.34
    if current_cf > 0:
        cf *= target_cf / current_cf

    cf = np.clip(cf, 0, 1)

    return cf


def generate_hydro(hours):
    """
    Generate normalized hydropower capacity factor.
    Based on monthly generation data - twelve constant values.
    Cuba has limited hydro (60 MW installed, 135 MW max).
    Higher in wet season (May-Oct), lower in dry season.
    """
    n = len(hours)

    # Monthly capacity factors (Cuba hydro - small run-of-river + reservoirs)
    monthly_cf = {
        1: 0.25,
        2: 0.22,
        3: 0.20,
        4: 0.20,
        5: 0.35,
        6: 0.45,
        7: 0.50,
        8: 0.50,
        9: 0.55,
        10: 0.50,
        11: 0.40,
        12: 0.30,
    }

    cf = np.array([monthly_cf[h.month] for h in hours])

    return cf


def generate_demand(hours):
    """
    Generate electricity demand time series for Cuba 2030.
    Projected annual demand: 27 TWh_el (from paper).
    Based on seasonal, weekly, and daily patterns.
    """
    n = len(hours)
    day_of_year = hours.dayofyear.values
    hour_of_day = hours.hour.values
    day_of_week = hours.dayofweek.values  # 0=Monday

    # Annual demand in MWh
    annual_demand_mwh = 27_000_000  # 27 TWh

    # Average hourly demand
    avg_demand = annual_demand_mwh / 8760  # ~3082 MW average

    # Seasonal pattern (Cuba: higher demand in summer due to cooling)
    seasonal = 1.0 + 0.15 * np.cos(2 * np.pi * (day_of_year - 200) / 365)

    # Weekly pattern (lower on weekends)
    weekly = np.where(day_of_week < 5, 1.0, 0.85)

    # Daily load profile (24 representative patterns from paper)
    # Simplified to a typical Cuban daily pattern
    hourly_profile = np.array(
        [
            0.70,  # 0
            0.65,  # 1
            0.62,  # 2
            0.60,  # 3
            0.60,  # 4
            0.62,  # 5
            0.70,  # 6
            0.80,  # 7
            0.88,  # 8
            0.92,  # 9
            0.95,  # 10
            0.97,  # 11
            0.95,  # 12
            0.90,  # 13
            0.88,  # 14
            0.85,  # 15
            0.85,  # 16
            0.88,  # 17
            0.95,  # 18
            1.00,  # 19 - evening peak
            0.98,  # 20
            0.92,  # 21
            0.85,  # 22
            0.78,  # 23
        ]
    )

    daily = hourly_profile[hour_of_day]

    # Combine patterns
    demand = avg_demand * seasonal * weekly * daily

    # Normalize to match annual total
    current_total = demand.sum()
    demand *= annual_demand_mwh / current_total

    return demand


if __name__ == "__main__":
    print("Generating time series for Cuba energy model...")

    solar = generate_solar_pv(hours)
    wind = generate_wind(hours)
    hydro = generate_hydro(hours)
    demand = generate_demand(hours)

    # Create DataFrame
    ts = pd.DataFrame(
        {
            "timestamp": hours,
            "solar_pv": solar,
            "wind": wind,
            "hydro": hydro,
            "demand_mwh": demand,
        }
    )

    ts.to_csv("/home/brian/Documents/Cuba/data/timeseries.csv", index=False)

    print(f"Solar PV - mean CF: {solar.mean():.3f}, max: {solar.max():.3f}")
    print(f"Wind     - mean CF: {wind.mean():.3f}, max: {wind.max():.3f}")
    print(f"Hydro    - mean CF: {hydro.mean():.3f}, max: {hydro.max():.3f}")
    print(f"Demand   - total: {demand.sum()/1e6:.1f} TWh, peak: {demand.max():.0f} MW, avg: {demand.mean():.0f} MW")
    print(f"\nSaved to data/timeseries.csv")
