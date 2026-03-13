# Cuba Energy System Model

Replication of "An energy system model-based approach to investigate cost-optimal technology mixes for the Cuban power system" (CURE Preprint, Reiner Lemoine Institut, 2024).

## Quick Start

```bash
pip install -r requirements.txt
python cuba_model.py              # Run all 6 scenarios
python cuba_model.py --scenario 4 # Run single scenario
```

## Project Structure

- `cuba_model.py` — Active working model with 2025 cost updates, DSM, pumped hydro option. All technology parameters defined as module-level dicts at the top.
- `improve_timeseries.py` — Generates timeseries from ninja source data (TZ fix, multi-site wind)
- `generate_timeseries.py` — Generates synthetic solar/wind/hydro/demand profiles (fallback if ninja data unavailable)
- `generate_demand.py` — Improved demand profile based on CubaLinda model and ONEI statistics
- `integrate_ninja_data.py` — Replaces synthetic RE profiles with real renewables.ninja satellite data
- `data/timeseries.csv` — Active input: 8760-row hourly time series (TZ-corrected, multi-site eastern Cuba wind)
- `data/ninja_solar_raw.csv`, `data/ninja_wind_raw.csv` — Real renewables.ninja capacity factors (2019, lat=22 lon=-79.5)
- `data/ninja_wind_*_raw.csv` — Eastern Cuba wind sites (Gibara, Las Tunas, Camagüey)

## Architecture

Single-node linear optimization model using oemof-solph:
- **Buses**: electricity, crude_oil, hfo, diesel, natural_gas, biomass
- **Sources**: fuel commodity sources, renewable generators (solar PV, wind, hydro)
- **Converters**: thermal power plants (oil, CCGT, diesel genset, HFO genset, bioelectric)
- **Storage**: Li-ion battery + pumped hydro (investment-optimized)
- **Sinks**: demand (fixed profile), excess/curtailment

## 6 Scenarios

1. BAU — existing capacities only, no investment
2. 37% RES Review — government expansion plan (fixed capacities from Table 1)
3. 37% RES Alternative — cost-optimal with 37% RES floor constraint
4. Cost-Optimal — unconstrained optimization (key scenario)
5. 100% RES Review — government 100% plan (typically infeasible)
6. 100% RES Alternative — cost-optimal with 100% RES constraint

## Solver

Uses HiGHS via pyomo's APPSI interface (`pyomo.contrib.appsi.solvers.Highs`). CBC is NOT supported (segfaults on some systems). The solver bypass is in `solve_model()` — it writes an LP and solves directly rather than going through oemof's `model.solve()`.

## Key Parameters to Experiment With

For solar optimization work, the most relevant parameters are in the module-level dicts:

- `RENEWABLES["solar_pv"]` — capex, installed capacity, max capacity
- `BATTERIES` / `BATTERY` — Li-ion storage costs, efficiency, c-rate
- `PUMPED_HYDRO` — pumped hydro storage costs, efficiency, capacity limits
- `FUEL_PRICES` — changing fuel costs shifts the cost-optimal RE share
- `TARGET_DEMAND_TWH` — annual demand target (currently 21.3 TWh)
- `DSM_SHIFT_FRACTION` — demand-side management evening-to-midday shift (currently 30%)
- `WACC` — discount rate (currently 7.5%)
- Solar capacity factors come from `data/timeseries.csv` column `solar_pv`

## RES Constraint

Custom pyomo constraint added in `solve_model()`. Reformulated as linear inequality:
```
RE_gen * (1 - target) >= nonRE_gen * target
```

## Results Reference

### Paper (Brandts et al. 2024, Table 6)

| Scenario | RES % | LCOE (ct/kWh) | Investment (Bn USD) |
|----------|-------|---------------|---------------------|
| 1 BAU | 3.9 | 11.6 | 0 |
| 2 37% Review | 37 | 9.5 | 4.0 |
| 4 Cost-Optimal | 83 | 7.3 | 9.3 |
| 6 100% Alt | 100 | 11.3 | 25.8 |

### Working Model (2025 costs, 21.3 TWh demand, DSM)

| Scenario | RES % | LCOE (ct/kWh) | Investment (Bn USD) |
|----------|-------|---------------|---------------------|
| 1 BAU | 24.5 | 8.8 | 0 |
| 4 Cost-Optimal | 85.6 | 6.0 | 5.6 |
| 6 100% Alt | 100 | 8.8 | 16.3 |

