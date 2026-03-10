"""
Cuba Energy System Model - Replication of CURE Preprint (Reiner Lemoine Institut)

Uses oemof-solph to model Cuba's electricity system and find cost-optimal
technology mixes under different renewable energy share (RES) constraints.

6 Scenarios:
1. BAU - Business as usual (no new investments)
2. 37% RES Target Review (government expansion plan)
3. 37% RES Target Alternative (cost-optimal with 37% RES constraint)
4. Overall Cost-Optimal (no RES constraint)
5. 100% RES Target Review (government plan - expected infeasible)
6. 100% RES Target Alternative (cost-optimal with 100% RES constraint)
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
# TECHNOLOGY PARAMETERS (from Tables 2-5 of the paper)
# ============================================================================

# Volatile renewables (Table 2)
RENEWABLES = {
    "solar_pv": {
        "capex_per_mw": 857_000,  # USD/MW (857 USD/kWp)
        "installed_cap": 230,  # MW
        "max_cap": None,  # No limit
        "lifetime": 30,
        "fix_opex": 10_000,  # USD/MW/year
        "var_opex": 0,
    },
    "wind": {
        "capex_per_mw": 1_325_000,  # USD/MW
        "installed_cap": 12,  # MW
        "max_cap": None,
        "lifetime": 20,
        "fix_opex": 44_500,  # USD/MW/year
        "var_opex": 0,
    },
    "hydro": {
        "capex_per_mw": 2_000_000,  # USD/MW
        "installed_cap": 60,  # MW
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

# Battery storage parameters (Table 5) - using c-rate = 1 as base
BATTERY = {
    "storage_capex_per_mwh": 211_000,  # USD/MWh (c-rate 1)
    "power_capex_per_mw": 51_500,  # USD/MW input power (c-rate 1)
    "storage_fix_opex": 2_750,  # USD/MWh/year
    "efficiency": 0.875,  # roundtrip = sqrt(0.875) charge * sqrt(0.875) discharge
    "lifetime": 20,
    "c_rate": 1,
}


def load_timeseries():
    """Load time series data."""
    ts = pd.read_csv(os.path.join(DATA_DIR, "timeseries.csv"))
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


def build_energy_system(scenario, ts):
    """
    Build the oemof energy system for a given scenario.

    Scenarios:
    1: BAU - no new investment allowed
    2: 37% RES target review - use government expansion targets as initial caps
    3: 37% RES target alternative - optimize with 37% RES constraint
    4: Overall cost-optimal - no RES constraint, full optimization
    5: 100% RES target review - use government 100% targets
    6: 100% RES target alternative - optimize with 100% RES constraint
    """
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
                        variable_costs=FUEL_PRICES[fuel_name],
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
    # Battery Storage
    # ========================================================================
    if allow_storage:
        storage_ann = annuity(BATTERY["storage_capex_per_mwh"], BATTERY["lifetime"])
        power_ann = annuity(BATTERY["power_capex_per_mw"], BATTERY["lifetime"])

        # In oemof-solph, GenericStorage with investment
        inflow_eff = np.sqrt(BATTERY["efficiency"])
        outflow_eff = np.sqrt(BATTERY["efficiency"])

        es.add(
            solph.components.GenericStorage(
                label="battery_storage",
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
                    ep_costs=storage_ann + BATTERY["storage_fix_opex"],
                ),
                loss_rate=0,
                inflow_conversion_factor=inflow_eff,
                outflow_conversion_factor=outflow_eff,
                balanced=True,  # Storage level same at start and end
                invest_relation_input_capacity=BATTERY["c_rate"],
                invest_relation_output_capacity=BATTERY["c_rate"],
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
                if label in ["electricity_excess", "battery_storage"]:
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
                    "battery_storage",
                ]:
                    continue

                flow_data = node_data["sequences"]["flow"]
                gen_total = flow_data.sum()
                generation[label] = gen_total

                # Get capacity (nominal_value or investment)
                if "scalars" in node_data and "invest" in node_data["scalars"]:
                    capacities[label] = node_data["scalars"]["invest"]

    # Storage results
    storage_capacity = 0
    storage_power = 0
    for node_label, node_data in results.items():
        from_node, to_node = node_label
        if hasattr(from_node, "label") and from_node.label == "battery_storage":
            if to_node is None:
                # Storage internal (capacity)
                if "scalars" in node_data and "invest" in node_data["scalars"]:
                    storage_capacity = node_data["scalars"]["invest"]
            elif hasattr(to_node, "label") and to_node.label == "electricity_bus":
                if "scalars" in node_data and "invest" in node_data["scalars"]:
                    storage_power = node_data["scalars"]["invest"]

    # Categorize renewable vs non-renewable generation
    re_labels = []
    for label in generation:
        base = label.replace("_existing", "").replace("_invest", "")
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

    # Storage investment
    if storage_capacity > 0:
        total_investment += storage_capacity * BATTERY["storage_capex_per_mwh"]
        total_investment += storage_power * BATTERY["power_capex_per_mw"]

    summary["res_share"] = res_share
    summary["total_generation_twh"] = total_generation / 1e6
    summary["re_generation_twh"] = re_generation / 1e6
    summary["generation"] = generation
    summary["new_capacities"] = capacities
    summary["storage_mwh"] = storage_capacity
    summary["storage_mw"] = storage_power
    summary["total_investment"] = total_investment

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
    # Objective is total system cost (annualized)
    lcoe = objective / (total_gen * 1e6) / 10 if total_gen > 0 else 0  # US cents/kWh
    print(f"  System cost:          {objective/1e9:.2f} Bn USD/year")
    print(f"  Average LCOE:         {lcoe:.1f} US cents/kWh_el")

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
        print(f"\n  Battery storage: {summary['storage_mwh']:.0f} MWh / {summary['storage_mw']:.0f} MW")

    print()
    return lcoe


def run_scenario(scenario_num, ts):
    """Run a single scenario."""
    print(f"\nBuilding Scenario {scenario_num}...")
    es, res_target = build_energy_system(scenario_num, ts)

    print(f"Solving Scenario {scenario_num}...")
    try:
        results, objective = solve_model(es, res_constraint=res_target)
        summary = extract_results(results, es, scenario_num, ts)
        lcoe = print_results(summary, objective)
        return summary, objective, lcoe
    except Exception as e:
        print(f"  Scenario {scenario_num} FAILED: {e}")
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
