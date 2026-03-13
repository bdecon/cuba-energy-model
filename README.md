# Cuba Energy System Model

Replication and extension of the CURE Preprint (Reiner Lemoine Institut, 2024): *"An energy system model-based approach to investigate cost-optimal technology mixes for the Cuban power system to meet national targets"* by Brandts, Bertheau, Rojas Plana, Lammers, and Rubio Rodriguez.

## What This Does

This model optimizes Cuba's electricity system for 2030 using linear programming. It evaluates 6 scenarios ranging from business-as-usual to 100% renewables, finding the cheapest mix of solar, wind, batteries, and conventional generators to meet hourly demand.

Key findings from the paper: the cost-optimal mix reaches ~83% renewables at 7.3 cents/kWh — cheaper than the current fossil-heavy system at 11.6 cents/kWh.

With updated 2025 costs (IRENA, Ember) and current Cuban commitments (2 GW solar, 427 MW wind), 100% renewables costs 8.8 cents/kWh — essentially the same as BAU — requiring $16.3 Bn in new investment (solar 58%, battery 16%, biomass 18%).

## Setup (Windows)

### 1. Install Python

Download Python 3.10+ from [python.org](https://www.python.org/downloads/). During installation, **check "Add Python to PATH"**.

### 2. Run setup

Double-click `setup.bat`, or open a terminal (PowerShell or Command Prompt) in this project folder and run:

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

> Every time you open a new terminal to work on this, run `venv\Scripts\activate` first.

### 3. Run the model

The most interesting scenario is **Scenario 6: 100% Renewable Cost-Optimal** — it finds the cheapest way to power Cuba entirely with renewables:

```powershell
python cuba_model.py --scenario 6
```

To run all 6 scenarios (takes several minutes):
```powershell
python cuba_model.py
```

For investment breakdown and sensitivity analysis:
```powershell
python calc_investment.py          # Scenario 6 investment breakdown
python sensitivity_analysis.py     # Fuel price sensitivity + donor-funded buildout
```

## Project Structure

```
cuba_model.py              Active working model (2025 costs, DSM, pumped hydro)
cuba_model_ref_utc.py      Frozen paper replication (UTC error, best paper match)
cuba_model_ref_local.py    Frozen paper replication (timezone-corrected)
cuba_model2.py             Kevin's version
calc_investment.py         Investment breakdown for Scenario 6
sensitivity_analysis.py    Fuel price sensitivity + phased buildout analysis
generate_timeseries.py     Synthetic time series generator (fallback)
generate_demand.py         Improved demand profiles
integrate_ninja_data.py    Swap in real renewables.ninja data
data/
  timeseries.csv           Active hourly input (TZ-corrected, multi-site wind)
  timeseries_ref_utc.csv   Frozen paper replication timeseries (UTC)
  timeseries_ref_local.csv Frozen paper replication timeseries (TZ-corrected)
  ninja_solar_raw.csv      Real solar capacity factors from renewables.ninja
  ninja_wind_raw.csv       Real wind capacity factors from renewables.ninja
  onei/                    Official Cuban energy statistics (ONEI 2024)
```

## How to Modify

All technology parameters are defined as Python dictionaries at the top of `cuba_model.py`:

- **`RENEWABLES`** — solar PV, wind, hydro: costs, capacities, lifetimes
- **`POWER_PLANTS`** — oil, gas, diesel, HFO, biomass plants
- **`BATTERIES`** / **`PUMPED_HYDRO`** — storage costs, efficiency, capacity limits
- **`FUEL_PRICES`** — cost of each fuel per MWh thermal
- **`TARGET_DEMAND_TWH`** — annual demand (21.3 TWh)
- **`DSM_SHIFT_FRACTION`** — evening-to-midday demand shift (30%)
- **`WACC`** — discount rate (7.5%)

For example, to test cheaper solar panels, change `RENEWABLES["solar_pv"]["capex_per_mw"]` from `691_000` to a lower value and re-run.

## Data Sources

- **Solar & wind profiles**: [renewables.ninja](https://www.renewables.ninja/) (satellite-derived, 2019 weather year, lat=22° lon=-79.5°)
- **Demand profile**: Synthesized from CubaLinda model (Luukkanen et al., 2022) and ONEI statistics
- **Technology costs**: Tables 2-5 of the CURE paper, updated with IRENA 2024 and Ember Oct 2025
- **Installed capacities**: ONEI Anuario Estadístico 2024

## Troubleshooting

**"No module named 'oemof'"** — Make sure your virtual environment is activated (`venv\Scripts\activate`).

**Solver errors** — The model uses HiGHS (installed via `highspy`). If you get solver errors, try `pip install --upgrade highspy`.

**"ModuleNotFoundError: No module named 'pyomo.contrib.appsi'"** — Run `pip install --upgrade pyomo`.
