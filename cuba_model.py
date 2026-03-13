"""
Cuba Energy System Model - Working version with improvements

Based on Brandts et al. (2024, Energy 306) with corrections and enhancements:
- Timezone-corrected solar/wind (UTC-5)
- Multi-site eastern Cuba wind data (Gibara, Las Tunas, Camagüey)
- Research-based hydro capacity factors
- Existing plant fixed O&M included in LCOE
- Battery + pumped hydro storage options

Reference versions (frozen, do not modify):
- cuba_model_ref_utc.py: Paper replication with UTC error (best paper match)
- cuba_model_ref_local.py: Paper replication with TZ correction

Timeseries: data/timeseries.csv (TZ-corrected, multi-site wind)
"""

import os
import warnings
import numpy as np
import pandas as pd
from oemof import solph

warnings.filterwarnings("ignore")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

# ============================================================================
# ECONOMIC PARAMETERS
# ============================================================================
PROJECT_DURATION = 20  # years
WACC = 0.075  # 7.5% weighted average cost of capital


def annuity(capex, lifetime, wacc=WACC):
    """Calculate annuity factor (capital recovery factor * capex)."""
    if wacc == 0:
        return capex / lifetime
    crf = (wacc * (1 + wacc) ** lifetime) / ((1 + wacc) ** lifetime - 1)
    return capex * crf


# ============================================================================
# TECHNOLOGY PARAMETERS
# Base: Brandts et al. (2024) Tables 2-5
# Updated: Kevin's 2025 assumptions + IRENA 2024 report (released Jul 2025)
# ============================================================================

# Volatile renewables (Table 2, with 2025 updates)
RENEWABLES = {
    "solar_pv": {
        "capex_per_mw": 691_000,  # USD/MW (IRENA 2024 global weighted avg, Jul 2025)
        "installed_cap": 2_000,  # MW (900 built + 1,100 committed, Kevin 2025)
        "max_cap": None,  # No limit
        "lifetime": 30,
        "fix_opex": 10_000,  # USD/MW/year
        "var_opex": 0,
    },
    "wind": {
        "capex_per_mw": 1_041_000,  # USD/MW (IRENA 2024 global weighted avg, Jul 2025)
        "installed_cap": 427,  # MW (12 built + 415 committed, Kevin 2025)
        "max_cap": None,
        "lifetime": 20,
        "fix_opex": 44_500,  # USD/MW/year
        "var_opex": 0,
    },
    "hydro": {
        "capex_per_mw": 2_000_000,  # USD/MW
        "installed_cap": 65,  # MW (Brandts Fig 1 correction, Kevin 2025)
        "max_cap": 135,  # MW (resource limit)
        "lifetime": 30,
        "fix_opex": 60_000,  # USD/MW/year
        "var_opex": 0,
    },
}

# Fuel source prices (Table 3) - USD/MWh_th
FUEL_PRICES = {
    "crude_oil": 34,
    "hfo": 77,
    "diesel": 93,
    "natural_gas": 32,
    "biomass": 9,
}

# Emission factors (Table 3) - kgCO2/MWh_th
EMISSION_FACTORS = {
    "crude_oil": 264,
    "hfo": 286,
    "diesel": 266,
    "natural_gas": 201,
    "biomass": 0,
}

# Transformer / power plant parameters (Table 4)
POWER_PLANTS = {
    "oil_power_plant": {
        "fuel": "crude_oil",
        "capex_per_mw": 812_500,
        "efficiency": 0.30,
        "installed_cap": 2608,
        "max_cap": None,
        "lifetime": 20,
        "fix_opex": 21_250,  # USD/MW/year
        "var_opex": 5,  # USD/MWh_el (dispatch price)
    },
    "ccgt": {
        "fuel": "natural_gas",
        "capex_per_mw": 1_000_000,
        "efficiency": 0.45,
        "installed_cap": 506,
        "max_cap": None,
        "lifetime": 20,
        "fix_opex": 16_500,
        "var_opex": 4,
    },
    "bioelectric": {
        "fuel": "biomass",
        "capex_per_mw": 2_500_000,
        "efficiency": 0.30,
        "installed_cap": 62,  # Only the new 62 MW plant
        "max_cap": 1220,  # Resource-based cap
        "lifetime": 20,
        "fix_opex": 37_500,
        "var_opex": 10,
    },
    "diesel_genset": {
        "fuel": "diesel",
        "capex_per_mw": 650_000,
        "efficiency": 0.39,
        "installed_cap": 1293,
        "max_cap": None,
        "lifetime": 20,
        "fix_opex": 10_000,
        "var_opex": 10,
    },
    "hfo_genset": {
        "fuel": "hfo",
        "capex_per_mw": 650_000,
        "efficiency": 0.39,
        "installed_cap": 1378,
        "max_cap": None,
        "lifetime": 20,
        "fix_opex": 10_000,
        "var_opex": 10,
    },
}

# Battery storage parameters (updated 2025)
# All-in installed cost of $125/kWh (Ember Oct 2025: $75 equipment + $50 install)
# c_rate=0.25 (4-hour battery) — power = capacity/4, realistic for grid-scale.
BATTERIES = [
    {
        "label": "battery_storage",
        "storage_capex_per_mwh": 125_000,  # USD/MWh all-in (Ember Oct 2025)
        "power_capex_per_mw": 0,  # USD/MW (folded into storage cost)
        "storage_fix_opex": 2_500,  # USD/MWh/year (~2% of CAPEX, Ember 2025)
        "efficiency": 0.875,  # roundtrip (applied on output)
        "lifetime": 20,
        "c_rate": 0.25,  # 4-hour battery (power = capacity / 4)
    },
]
BATTERY = BATTERIES[0]

# Pumped hydro storage (Saunders et al. 2026; PNNL 2022; NREL ATB 2024)
# Cuba has 25 identified sites with ~20 GW potential (CubaLinda)
PUMPED_HYDRO = {
    "label": "pumped_hydro_storage",
    "storage_capex_per_mwh": 142_000,   # USD/MWh (PNNL 2022)
    "power_capex_per_mw": 1_100_000,    # USD/MW (NREL ATB 2024)
    "power_fix_opex": 18_000,           # USD/MW/year (NREL ATB 2024)
    "efficiency": 0.80,                 # roundtrip
    "lifetime": 60,                     # years (key advantage over Li-ion)
    "c_rate": 0.1,                      # 10-hour system
    "max_storage_mwh": 40_000,          # Upper bound (CubaLinda Scenario 1)
    "max_power_mw": 4_000,              # Upper bound
}


# ============================================================================
# DEMAND SCALING AND DSM PARAMETERS (Kevin 2025)
# ============================================================================
TARGET_DEMAND_TWH = 21.3  # 19 TWh consumption + 11% T&D losses (post-grid-modernization)
DSM_SHIFT_FRACTION = 0.30  # 30% of evening peak demand shifted to midday
DSM_EVENING_HOURS = (18, 19, 20, 21)  # 6pm-9pm
DSM_MIDDAY_HOURS = (10, 11, 12, 13)  # 10am-1pm


def load_timeseries():
    """Load time series data, scale demand to 21 TWh, and apply DSM."""
    ts = pd.read_csv(os.path.join(DATA_DIR, "timeseries.csv"))

    # Scale demand from base profile to target
    original_total = ts["demand_mwh"].sum()
    scale_factor = TARGET_DEMAND_TWH * 1e6 / original_total
    ts["demand_mwh"] = ts["demand_mwh"] * scale_factor

    # Apply DSM: shift 30% of evening demand to midday
    ts["hour"] = pd.to_datetime(ts["timestamp"]).dt.hour

    evening_mask = ts["hour"].isin(DSM_EVENING_HOURS)
    midday_mask = ts["hour"].isin(DSM_MIDDAY_HOURS)

    energy_removed = ts.loc[evening_mask, "demand_mwh"].values * DSM_SHIFT_FRACTION
    total_shifted = energy_removed.sum()

    # Remove 30% from evening hours
    ts.loc[evening_mask, "demand_mwh"] *= (1 - DSM_SHIFT_FRACTION)

    # Distribute shifted energy proportionally across midday hours
    midday_demand = ts.loc[midday_mask, "demand_mwh"].values
    midday_total = midday_demand.sum()
    ts.loc[midday_mask, "demand_mwh"] += total_shifted * (midday_demand / midday_total)

    ts.drop(columns=["hour"], inplace=True)
    return ts


def calc_dispatch_cost(plant_key):
    """Calculate total variable cost (fuel + var_opex) per MWh_el."""
    plant = POWER_PLANTS[plant_key]
    fuel_price = FUEL_PRICES[plant["fuel"]]  # USD/MWh_th
    fuel_cost_per_mwh_el = fuel_price / plant["efficiency"]
    return fuel_cost_per_mwh_el + plant["var_opex"]


def calc_annual_fixed_cost(capex, lifetime, fix_opex):
    """Calculate annualized fixed cost per MW (annuity + fix OPEX)."""
    return annuity(capex, lifetime) + fix_opex


def build_energy_system(scenario, ts, fuel_prices=None,
                        extra_solar_mw=0, extra_battery_mwh=0):
    """
    Build the oemof energy system for a given scenario.

    Scenarios:
    1: BAU - no new investment allowed
    2: 37% RES target review - use government expansion targets as initial caps
    3: 37% RES target alternative - optimize with 37% RES constraint
    4: Overall cost-optimal - no RES constraint, full optimization
    5: 100% RES target review - use government 100% targets
    6: 100% RES target alternative - optimize with 100% RES constraint

    Optional overrides for sensitivity analysis:
    fuel_prices: dict of fuel prices (defaults to FUEL_PRICES)
    extra_solar_mw: additional fixed solar capacity (MW)
    extra_battery_mwh: additional fixed battery capacity (MWh)
    """
    fuel_prices = fuel_prices if fuel_prices is not None else FUEL_PRICES

    date_range = pd.date_range("2030-01-01", periods=8760, freq="h")
    es = solph.EnergySystem(timeindex=date_range, infer_last_interval=True)

    # ========================================================================
    # Buses
    # ========================================================================
    b_electricity = solph.Bus(label="electricity_bus")
    b_crude_oil = solph.Bus(label="crude_oil_bus")
    b_hfo = solph.Bus(label="hfo_bus")
    b_diesel = solph.Bus(label="diesel_bus")
    b_natural_gas = solph.Bus(label="natural_gas_bus")
    b_biomass = solph.Bus(label="biomass_bus")

    es.add(b_electricity, b_crude_oil, b_hfo, b_diesel, b_natural_gas, b_biomass)

    fuel_buses = {
        "crude_oil": b_crude_oil,
        "hfo": b_hfo,
        "diesel": b_diesel,
        "natural_gas": b_natural_gas,
        "biomass": b_biomass,
    }

    # ========================================================================
    # Fuel Sources (commodity sources with fuel price as variable cost)
    # ========================================================================
    for fuel_name, bus in fuel_buses.items():
        es.add(
            solph.components.Source(
                label=f"source_{fuel_name}",
                outputs={
                    bus: solph.Flow(
                        variable_costs=fuel_prices[fuel_name],
                    )
                },
            )
        )

    # ========================================================================
    # Electricity Demand (Sink)
    # ========================================================================
    es.add(
        solph.components.Sink(
            label="electricity_demand",
            inputs={
                b_electricity: solph.Flow(
                    nominal_value=1,
                    fix=ts["demand_mwh"].values,
                )
            },
        )
    )

    # Excess electricity sink (curtailment)
    es.add(
        solph.components.Sink(
            label="electricity_excess",
            inputs={b_electricity: solph.Flow()},
        )
    )

    # ========================================================================
    # Determine capacities based on scenario
    # ========================================================================
    # Scenario-specific capacity settings
    allow_investment = scenario in [3, 4, 6]
    res_constraint = None

    if scenario == 1:
        # BAU: existing capacities only, no investment
        re_caps = {k: v["installed_cap"] for k, v in RENEWABLES.items()}
        pp_caps = {k: v["installed_cap"] for k, v in POWER_PLANTS.items()}
        allow_storage = False

    elif scenario == 2:
        # 37% RES target review: government expansion targets (Table 1)
        re_caps = {"solar_pv": 2104, "wind": 807, "hydro": 116}
        pp_caps = {
            "oil_power_plant": 2608,
            "ccgt": 506,
            "bioelectric": 612,
            "diesel_genset": 1293,
            "hfo_genset": 1378,
        }
        allow_storage = False
        res_constraint = 0.37

    elif scenario == 3:
        # 37% RES alternative: optimize with 37% constraint
        re_caps = {k: v["installed_cap"] for k, v in RENEWABLES.items()}
        pp_caps = {k: v["installed_cap"] for k, v in POWER_PLANTS.items()}
        allow_storage = True
        res_constraint = 0.37

    elif scenario == 4:
        # Overall cost-optimal: no constraint
        re_caps = {k: v["installed_cap"] for k, v in RENEWABLES.items()}
        pp_caps = {k: v["installed_cap"] for k, v in POWER_PLANTS.items()}
        allow_storage = True

    elif scenario == 5:
        # 100% RES target review: government 100% targets (Table 1)
        re_caps = {"solar_pv": 13000, "wind": 1800, "hydro": 56}
        pp_caps = {
            "oil_power_plant": 2608,
            "ccgt": 506,
            "bioelectric": 612,
            "diesel_genset": 1293,
            "hfo_genset": 1378,
        }
        allow_storage = True
        res_constraint = 1.0

    elif scenario == 6:
        # 100% RES alternative: optimize with 100% constraint
        re_caps = {k: v["installed_cap"] for k, v in RENEWABLES.items()}
        pp_caps = {k: v["installed_cap"] for k, v in POWER_PLANTS.items()}
        allow_storage = True
        res_constraint = 1.0

    # ========================================================================
    # Volatile Renewable Sources
    # ========================================================================
    re_ts_map = {"solar_pv": "solar_pv", "wind": "wind", "hydro": "hydro"}

    for re_name, re_params in RENEWABLES.items():
        cf_series = ts[re_ts_map[re_name]].values
        ann_fixed = calc_annual_fixed_cost(
            re_params["capex_per_mw"], re_params["lifetime"], re_params["fix_opex"]
        )

        if allow_investment:
            # Existing capacity as fixed, allow investment for additional
            existing = re_params["installed_cap"]
            max_invest = None
            if re_params["max_cap"] is not None:
                max_invest = max(0, re_params["max_cap"] - existing)

            # Fixed existing capacity
            if existing > 0:
                es.add(
                    solph.components.Source(
                        label=f"{re_name}_existing",
                        outputs={
                            b_electricity: solph.Flow(
                                nominal_value=existing,
                                max=cf_series,
                                variable_costs=re_params["var_opex"],
                            )
                        },
                    )
                )

            # Investable additional capacity
            invest_kwargs = {"ep_costs": ann_fixed}
            if max_invest is not None:
                invest_kwargs["maximum"] = max_invest

            es.add(
                solph.components.Source(
                    label=f"{re_name}_invest",
                    outputs={
                        b_electricity: solph.Flow(
                            max=cf_series,
                            variable_costs=re_params["var_opex"],
                            nominal_value=solph.Investment(**invest_kwargs),
                        )
                    },
                )
            )
        else:
            # Fixed capacity only
            cap = re_caps.get(re_name, re_params["installed_cap"])
            if cap > 0:
                es.add(
                    solph.components.Source(
                        label=re_name,
                        outputs={
                            b_electricity: solph.Flow(
                                nominal_value=cap,
                                max=cf_series,
                                variable_costs=re_params["var_opex"],
                            )
                        },
                    )
                )

    # ========================================================================
    # Conventional Power Plants (Transformers: fuel bus -> electricity bus)
    # ========================================================================
    for pp_name, pp_params in POWER_PLANTS.items():
        fuel_bus = fuel_buses[pp_params["fuel"]]
        dispatch_var_cost = pp_params["var_opex"]  # fuel cost handled at source
        ann_fixed = calc_annual_fixed_cost(
            pp_params["capex_per_mw"], pp_params["lifetime"], pp_params["fix_opex"]
        )

        if allow_investment:
            existing = pp_params["installed_cap"]
            max_invest = None
            if pp_params["max_cap"] is not None:
                max_invest = max(0, pp_params["max_cap"] - existing)

            # Fixed existing capacity
            if existing > 0:
                es.add(
                    solph.components.Converter(
                        label=f"{pp_name}_existing",
                        inputs={fuel_bus: solph.Flow()},
                        outputs={
                            b_electricity: solph.Flow(
                                nominal_value=existing,
                                variable_costs=dispatch_var_cost,
                            )
                        },
                        conversion_factors={b_electricity: pp_params["efficiency"]},
                    )
                )

            # Investable additional capacity
            if max_invest is None or max_invest > 0:
                invest_kwargs = {"ep_costs": ann_fixed}
                if max_invest is not None:
                    invest_kwargs["maximum"] = max_invest

                es.add(
                    solph.components.Converter(
                        label=f"{pp_name}_invest",
                        inputs={fuel_bus: solph.Flow()},
                        outputs={
                            b_electricity: solph.Flow(
                                nominal_value=solph.Investment(**invest_kwargs),
                                variable_costs=dispatch_var_cost,
                            )
                        },
                        conversion_factors={b_electricity: pp_params["efficiency"]},
                    )
                )
        else:
            # Fixed capacity
            cap = pp_caps.get(pp_name, pp_params["installed_cap"])
            if cap > 0:
                es.add(
                    solph.components.Converter(
                        label=pp_name,
                        inputs={fuel_bus: solph.Flow()},
                        outputs={
                            b_electricity: solph.Flow(
                                nominal_value=cap,
                                variable_costs=dispatch_var_cost,
                            )
                        },
                        conversion_factors={b_electricity: pp_params["efficiency"]},
                    )
                )

    # ========================================================================
    # Battery Storage (three c-rate options, optimizer chooses mix)
    # ========================================================================
    if allow_storage:
        for batt in BATTERIES:
            storage_ann = annuity(batt["storage_capex_per_mwh"], batt["lifetime"])
            power_ann = annuity(batt["power_capex_per_mw"], batt["lifetime"])

            # Paper applies 87.5% efficiency entirely on output side
            inflow_eff = 1.0
            outflow_eff = batt["efficiency"]

            es.add(
                solph.components.GenericStorage(
                    label=batt["label"],
                    inputs={
                        b_electricity: solph.Flow(
                            nominal_value=solph.Investment(ep_costs=power_ann),
                        )
                    },
                    outputs={
                        b_electricity: solph.Flow(
                            nominal_value=solph.Investment(ep_costs=0),
                        )
                    },
                    nominal_storage_capacity=solph.Investment(
                        ep_costs=storage_ann + batt["storage_fix_opex"],
                    ),
                    loss_rate=0,
                    inflow_conversion_factor=inflow_eff,
                    outflow_conversion_factor=outflow_eff,
                    balanced=True,
                    invest_relation_input_capacity=batt["c_rate"],
                    invest_relation_output_capacity=batt["c_rate"],
                )
            )

    # ========================================================================
    # Pumped Hydro Storage (investment-optimized, with capacity limit)
    # ========================================================================
    if allow_storage:
        ph = PUMPED_HYDRO
        ph_storage_ann = annuity(ph["storage_capex_per_mwh"], ph["lifetime"])
        ph_power_ann = annuity(ph["power_capex_per_mw"], ph["lifetime"]) + ph["power_fix_opex"]

        es.add(
            solph.components.GenericStorage(
                label=ph["label"],
                inputs={
                    b_electricity: solph.Flow(
                        nominal_value=solph.Investment(
                            ep_costs=ph_power_ann,
                            maximum=ph["max_power_mw"],
                        ),
                    )
                },
                outputs={
                    b_electricity: solph.Flow(
                        nominal_value=solph.Investment(ep_costs=0),
                    )
                },
                nominal_storage_capacity=solph.Investment(
                    ep_costs=ph_storage_ann,
                    maximum=ph["max_storage_mwh"],
                ),
                loss_rate=0,
                inflow_conversion_factor=1.0,
                outflow_conversion_factor=ph["efficiency"],
                balanced=True,
                invest_relation_input_capacity=ph["c_rate"],
                invest_relation_output_capacity=ph["c_rate"],
            )
        )

    # ========================================================================
    # Additional fixed capacity (for phased buildout / sensitivity analysis)
    # ========================================================================
    if extra_solar_mw > 0:
        es.add(
            solph.components.Source(
                label="solar_pv_added",
                outputs={
                    b_electricity: solph.Flow(
                        nominal_value=extra_solar_mw,
                        max=ts["solar_pv"].values,
                        variable_costs=0,
                    )
                },
            )
        )

    if extra_battery_mwh > 0:
        batt = BATTERY
        power_mw = extra_battery_mwh * batt["c_rate"]
        es.add(
            solph.components.GenericStorage(
                label="battery_added",
                inputs={b_electricity: solph.Flow(nominal_value=power_mw)},
                outputs={b_electricity: solph.Flow(nominal_value=power_mw)},
                nominal_storage_capacity=extra_battery_mwh,
                loss_rate=0,
                inflow_conversion_factor=1.0,
                outflow_conversion_factor=batt["efficiency"],
                balanced=True,
            )
        )

    return es, res_constraint


def solve_model(es, res_constraint=None, solver="highs"):
    """
    Solve the energy system optimization, optionally with RES constraint.

    The RES constraint enforces:
        sum(RE_generation) >= res_target * sum(total_generation)
    Reformulated as:
        sum(RE_gen) * (1 - target) - sum(nonRE_gen) * target >= 0
    """
    import pyomo.environ as po

    model = solph.Model(es)

    if res_constraint is not None and res_constraint > 0:
        # Identify renewable and non-renewable flows to electricity bus
        e_bus = None
        for node in es.nodes:
            if hasattr(node, "label") and node.label == "electricity_bus":
                e_bus = node
                break

        re_flows = []
        nonre_flows = []
        re_names = {"solar_pv", "wind", "hydro", "bioelectric"}

        for node in es.nodes:
            if not hasattr(node, "label"):
                continue
            label = node.label
            base_name = label.replace("_existing", "").replace("_invest", "")

            # Check if this node has output to electricity bus
            if hasattr(node, "outputs") and e_bus in node.outputs:
                # Skip excess and storage
                if label == "electricity_excess" or label.startswith("battery_") or label.startswith("pumped_hydro"):
                    continue
                if base_name in re_names:
                    re_flows.append((node, e_bus))
                else:
                    nonre_flows.append((node, e_bus))

        # Add constraint: sum(RE) >= target * sum(RE + nonRE)
        # => sum(RE) * (1 - target) >= sum(nonRE) * target
        target = res_constraint

        def res_rule(m):
            re_sum = 0
            nonre_sum = 0
            for src, snk in re_flows:
                re_sum += sum(m.flow[src, snk, t] for t in m.TIMESTEPS)
            for src, snk in nonre_flows:
                nonre_sum += sum(m.flow[src, snk, t] for t in m.TIMESTEPS)
            return re_sum * (1 - target) >= nonre_sum * target

        model.res_constraint = po.Constraint(rule=res_rule)

    if solver == "highs":
        # Write LP file and solve with HiGHS via highspy directly,
        # then read results back into pyomo
        import tempfile
        lp_path = os.path.join(tempfile.gettempdir(), "cuba_model.lp")
        model.write(lp_path, io_options={"symbolic_solver_labels": True})
        import highspy
        h = highspy.Highs()
        h.setOptionValue("output_flag", False)
        h.readModel(lp_path)
        h.run()
        # Read solution back - use pyomo's mechanism
        sol_path = lp_path.replace(".lp", ".sol")
        # Actually, let's use pyomo's appsi_highs interface properly
        from pyomo.contrib.appsi.solvers import Highs as AppsiHighs
        opt = AppsiHighs()
        opt.config.stream_solver = False
        opt.solve(model)
    else:
        model.solve(solver=solver, solve_kwargs={"tee": False})
    return solph.processing.results(model), model.objective()


def extract_results(results, es, scenario, ts):
    """Extract and summarize results from solved model."""
    summary = {"scenario": scenario}

    total_demand = ts["demand_mwh"].sum()

    # Collect generation by technology
    generation = {}
    capacities = {}

    for node_label, node_data in results.items():
        from_node, to_node = node_label

        if to_node is not None and hasattr(to_node, "label"):
            if to_node.label == "electricity_bus":
                label = from_node.label if hasattr(from_node, "label") else str(from_node)

                if label in [
                    "electricity_excess",
                    "electricity_demand",
                ] or label.startswith("battery_") or label.startswith("pumped_hydro"):
                    continue

                flow_data = node_data["sequences"]["flow"]
                gen_total = flow_data.sum()
                generation[label] = gen_total

                # Get capacity (nominal_value or investment)
                if "scalars" in node_data and "invest" in node_data["scalars"]:
                    capacities[label] = node_data["scalars"]["invest"]

    # Storage results (batteries + pumped hydro)
    storage_capacity = 0
    storage_power = 0
    storage_details = {}
    all_storage_labels = {b["label"] for b in BATTERIES} | {PUMPED_HYDRO["label"]}
    for node_label, node_data in results.items():
        from_node, to_node = node_label
        if hasattr(from_node, "label") and from_node.label in all_storage_labels:
            slabel = from_node.label
            if to_node is None:
                if "scalars" in node_data and "invest" in node_data["scalars"]:
                    cap = node_data["scalars"]["invest"]
                    storage_capacity += cap
                    storage_details[slabel] = {"mwh": cap}
            elif hasattr(to_node, "label") and to_node.label == "electricity_bus":
                if "scalars" in node_data and "invest" in node_data["scalars"]:
                    pwr = node_data["scalars"]["invest"]
                    storage_power += pwr
                    if slabel in storage_details:
                        storage_details[slabel]["mw"] = pwr

    # Categorize renewable vs non-renewable generation
    re_labels = []
    for label in generation:
        base = label.replace("_existing", "").replace("_invest", "").replace("_added", "")
        if base in ["solar_pv", "wind", "hydro", "bioelectric"]:
            re_labels.append(label)

    re_generation = sum(generation.get(l, 0) for l in re_labels)
    total_generation = sum(generation.values())
    res_share = re_generation / total_generation if total_generation > 0 else 0

    # Calculate total initial investment (capex * new capacity)
    total_investment = 0

    if scenario in [2, 5]:
        # Fixed-capacity scenarios: investment = (target - installed) * capex
        if scenario == 2:
            re_targets = {"solar_pv": 2104, "wind": 807, "hydro": 116}
            pp_targets = {"bioelectric": 612}
        else:  # scenario 5
            re_targets = {"solar_pv": 13000, "wind": 1800, "hydro": 56}
            pp_targets = {"bioelectric": 612}
        for name, target in re_targets.items():
            added = max(0, target - RENEWABLES[name]["installed_cap"])
            total_investment += added * RENEWABLES[name]["capex_per_mw"]
        for name, target in pp_targets.items():
            added = max(0, target - POWER_PLANTS[name]["installed_cap"])
            total_investment += added * POWER_PLANTS[name]["capex_per_mw"]
    else:
        for label, cap in capacities.items():
            if cap < 0.1:
                continue
            base = label.replace("_invest", "")
            if base in RENEWABLES:
                total_investment += cap * RENEWABLES[base]["capex_per_mw"]
            elif base in POWER_PLANTS:
                total_investment += cap * POWER_PLANTS[base]["capex_per_mw"]

    # Storage investment (batteries + pumped hydro)
    storage_lookup = {b["label"]: b for b in BATTERIES}
    storage_lookup[PUMPED_HYDRO["label"]] = PUMPED_HYDRO
    for slabel, sdata in storage_details.items():
        sparams = storage_lookup[slabel]
        total_investment += sdata.get("mwh", 0) * sparams["storage_capex_per_mwh"]
        total_investment += sdata.get("mw", 0) * sparams.get("power_capex_per_mw", 0)

    # Calculate fixed O&M for existing plants (not in optimizer objective)
    # These are real ongoing costs that affect LCOE but not dispatch decisions
    existing_fixed_om = 0
    if scenario in [3, 4, 6]:
        # Investment scenarios: existing capacity = installed_cap from params
        for re_name, re_params in RENEWABLES.items():
            existing_fixed_om += re_params["installed_cap"] * re_params["fix_opex"]
        for pp_name, pp_params in POWER_PLANTS.items():
            existing_fixed_om += pp_params["installed_cap"] * pp_params["fix_opex"]
    elif scenario == 1:
        # BAU: all capacity is existing
        for re_name, re_params in RENEWABLES.items():
            existing_fixed_om += re_params["installed_cap"] * re_params["fix_opex"]
        for pp_name, pp_params in POWER_PLANTS.items():
            existing_fixed_om += pp_params["installed_cap"] * pp_params["fix_opex"]
    elif scenario == 2:
        re_caps_s2 = {"solar_pv": 2104, "wind": 807, "hydro": 116}
        pp_caps_s2 = {
            "oil_power_plant": 2608, "ccgt": 506, "bioelectric": 612,
            "diesel_genset": 1293, "hfo_genset": 1378,
        }
        for name, cap in re_caps_s2.items():
            existing_fixed_om += cap * RENEWABLES[name]["fix_opex"]
        for name, cap in pp_caps_s2.items():
            existing_fixed_om += cap * POWER_PLANTS[name]["fix_opex"]
    elif scenario == 5:
        re_caps_s5 = {"solar_pv": 13000, "wind": 1800, "hydro": 56}
        pp_caps_s5 = {
            "oil_power_plant": 2608, "ccgt": 506, "bioelectric": 612,
            "diesel_genset": 1293, "hfo_genset": 1378,
        }
        for name, cap in re_caps_s5.items():
            existing_fixed_om += cap * RENEWABLES[name]["fix_opex"]
        for name, cap in pp_caps_s5.items():
            existing_fixed_om += cap * POWER_PLANTS[name]["fix_opex"]

    summary["res_share"] = res_share
    summary["total_generation_twh"] = total_generation / 1e6
    summary["re_generation_twh"] = re_generation / 1e6
    summary["generation"] = generation
    summary["new_capacities"] = capacities
    summary["storage_mwh"] = storage_capacity
    summary["storage_mw"] = storage_power
    summary["storage_details"] = storage_details
    summary["total_investment"] = total_investment
    summary["existing_fixed_om"] = existing_fixed_om

    return summary


def print_results(summary, objective):
    """Print formatted results."""
    scenario = summary["scenario"]
    scenario_names = {
        1: "BAU (Business as Usual)",
        2: "37% RES Target Review",
        3: "37% RES Target Alternative",
        4: "Overall Cost-Optimal",
        5: "100% RES Target Review",
        6: "100% RES Target Alternative",
    }

    print(f"\n{'='*70}")
    print(f"  SCENARIO {scenario}: {scenario_names[scenario]}")
    print(f"{'='*70}")

    total_gen = summary["total_generation_twh"]
    print(f"\n  Total generation:     {total_gen:.2f} TWh")
    print(f"  RES share:            {summary['res_share']*100:.1f}%")

    # LCOE calculation
    # Objective is total system cost (annualized) but excludes existing plant fixed O&M
    existing_fom = summary.get("existing_fixed_om", 0)
    full_system_cost = objective + existing_fom
    lcoe = full_system_cost / (total_gen * 1e6) / 10 if total_gen > 0 else 0  # US cents/kWh
    print(f"  System cost (optimizer):  {objective/1e9:.2f} Bn USD/year")
    print(f"  Existing plant fixed O&M: {existing_fom/1e6:.0f} M USD/year")
    print(f"  Full system cost:         {full_system_cost/1e9:.2f} Bn USD/year")
    print(f"  Average LCOE:             {lcoe:.1f} US cents/kWh_el")

    # Generation breakdown
    print(f"\n  Generation by technology:")
    print(f"  {'Technology':<30} {'Generation (TWh)':>15} {'Share':>8}")
    print(f"  {'-'*55}")

    gen = summary["generation"]
    total = sum(gen.values())
    for label, value in sorted(gen.items(), key=lambda x: -x[1]):
        share = value / total * 100 if total > 0 else 0
        print(f"  {label:<30} {value/1e6:>15.2f} {share:>7.1f}%")

    # New capacities
    if summary["new_capacities"]:
        print(f"\n  New investments:")
        for label, cap in summary["new_capacities"].items():
            if cap > 0.1:
                print(f"    {label}: {cap:.0f} MW")

    if summary["storage_mwh"] > 0:
        print(f"\n  Storage total: {summary['storage_mwh']:.0f} MWh / {summary['storage_mw']:.0f} MW")
        for slabel, sdata in summary.get("storage_details", {}).items():
            mwh = sdata.get("mwh", 0)
            mw = sdata.get("mw", 0)
            if mwh > 0.1:
                print(f"    {slabel}: {mwh:.0f} MWh / {mw:.0f} MW")

    print()
    return lcoe


def run_scenario(scenario_num, ts):
    """Run a single scenario."""
    import time

    scenario_names = {
        1: "BAU (Business as Usual)",
        2: "37% RES Target Review",
        3: "37% RES Target Alternative",
        4: "Overall Cost-Optimal",
        5: "100% RES Target Review",
        6: "100% RES Target Alternative",
    }

    name = scenario_names.get(scenario_num, f"Scenario {scenario_num}")
    print(f"\n  Building Scenario {scenario_num}: {name}...")
    es, res_target = build_energy_system(scenario_num, ts)

    print(f"  Solving (this can take 1-3 minutes)...", end="", flush=True)
    t0 = time.time()
    try:
        results, objective = solve_model(es, res_constraint=res_target)
        elapsed = time.time() - t0
        print(f" done in {elapsed:.0f}s")
        summary = extract_results(results, es, scenario_num, ts)
        lcoe = print_results(summary, objective)
        return summary, objective, lcoe
    except Exception as e:
        elapsed = time.time() - t0
        print(f" FAILED after {elapsed:.0f}s")
        print(f"  Error: {e}")
        return None, None, None


def main():
    print("=" * 70)
    print("  CUBA ENERGY SYSTEM MODEL")
    print("  Replication of CURE Preprint (Reiner Lemoine Institut, 2024)")
    print("=" * 70)

    ts = load_timeseries()
    print(f"\nLoaded time series: {len(ts)} hours")
    print(f"Annual demand: {ts['demand_mwh'].sum()/1e6:.1f} TWh")
    print(f"Peak demand: {ts['demand_mwh'].max():.0f} MW")

    all_results = {}

    # Run scenarios
    for s in [1, 2, 3, 4, 6]:  # Skip 5 (expected infeasible)
        result = run_scenario(s, ts)
        all_results[s] = result

    # Try scenario 5
    print("\nAttempting Scenario 5 (100% RES Target Review)...")
    print("  (Expected to be infeasible per the paper)")
    result = run_scenario(5, ts)
    all_results[5] = result

    # Summary comparison table
    print("\n" + "=" * 70)
    print("  SUMMARY COMPARISON (cf. Table 6 in paper)")
    print("=" * 70)
    print(f"  {'Scenario':<35} {'RES':>6} {'LCOE':>12} {'Investment':>12}")
    print(f"  {'':35} {'[%]':>6} {'[ct/kWh]':>12} {'[Bn USD]':>12}")
    print(f"  {'-'*65}")

    paper_values = {
        1: (3.9, 11.6, 0),
        2: (37, 9.5, 4),
        3: (37, 8.0, 5.9),
        4: (83, 7.3, 9.3),
        5: (100, None, None),
        6: (100, 11.3, 25.8),
    }

    for s in [1, 2, 3, 4, 5, 6]:
        if all_results.get(s) and all_results[s][0] is not None:
            summary, obj, lcoe = all_results[s]
            res = summary["res_share"] * 100
            inv = summary["total_investment"] / 1e9
            print(f"  Scenario {s:<29} {res:>5.1f} {lcoe:>11.1f} {inv:>11.1f}")

            pv = paper_values[s]
            print(
                f"    Paper values:{'':>14} {pv[0]:>5.1f} "
                f"{'N/A' if pv[1] is None else f'{pv[1]:>11.1f}'} "
                f"{'N/A' if pv[2] is None else f'{pv[2]:>11.1f}'}"
            )
        else:
            print(f"  Scenario {s:<29} {'INFEASIBLE':>30}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Cuba Energy System Model")
    parser.add_argument(
        "--scenario", type=int, choices=[1, 2, 3, 4, 5, 6],
        help="Run a single scenario (default: run all)",
    )
    args = parser.parse_args()

    if args.scenario:
        ts = load_timeseries()
        print(f"Loaded time series: {len(ts)} hours")
        print(f"Annual demand: {ts['demand_mwh'].sum()/1e6:.1f} TWh")
        run_scenario(args.scenario, ts)
    else:
        main()
