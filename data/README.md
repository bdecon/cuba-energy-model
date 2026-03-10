# Data Files

## Included in repo

- `timeseries.csv` — 8760-hour input time series (solar CF, wind CF, hydro CF, demand in MW). Ready to use.
- `ninja_solar_raw.csv` — Solar PV capacity factors from [renewables.ninja](https://www.renewables.ninja/) (lat=22, lon=-79.5, tilt=22°, azimuth=180°, 10% losses, 2019)
- `ninja_wind_raw.csv` — Wind capacity factors from renewables.ninja (Goldwind GW109/2500, 90m hub height, 2019)

## Must download separately

### ONEI Energy Statistics

The model references official Cuban energy statistics for validation. Download from:

**Source**: ONEI (Oficina Nacional de Estadísticas e Información de Cuba)
**File**: Anuario Estadístico de Cuba 2024, Chapter 10: "Minería y Energía"

1. Go to https://www.onei.gob.cu/anuario-estadistico-de-cuba-2024
2. Download the Excel RAR archive (link at bottom of page: "compressed file containing all chapter tables in EXCEL format")
3. Extract `10 Mineria y Energia_AEC2024.xlsx` from the RAR
4. Place it in `data/onei/`

Key sheets: 10.14 (electricity balance), 10.15-17 (generation by source), 10.18-19 (installed capacity by plant type).

This file is used for validation only — the model runs fine without it.

### Research Paper

The paper being replicated is not included in the repo:

**Citation**: Brandts, M., Bertheau, P., Rojas Plana, D., Lammers, K., & Rubio Rodriguez, M.A. (2024). *An energy system model-based approach to investigate cost-optimal technology mixes for the Cuban power system to meet national targets.* CURE Preprint, Reiner Lemoine Institut.

Search for "CURE Preprint Reiner Lemoine Institut Cuba" to find it.
