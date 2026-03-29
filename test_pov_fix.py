"""Quick test to verify POV agent symbol fix."""
import time
from abides_markets.config_system.models import SimulationConfig
from abides_markets.simulation import ResultProfile, run_simulation
import pandas as pd

config_dict = {
    "simulation": {"name": "pov_fix_test", "log_level": "ERROR", "seed": 42},
    "market": {
        "ticker": "ABM",
        "date": "20210205",
        "start_time": "09:30:00",
        "end_time": "12:00:00",
        "opening_price": 10000,
        "oracle": {"type": "sparse_mean_reverting"},
    },
    "infrastructure": {
        "latency": {"type": "no_latency"},
        "default_computation_delay": 1000000,
    },
    "agents": {
        "noise": {"enabled": True, "count": 100, "params": {}},
        "value": {
            "enabled": True,
            "count": 10,
            "params": {"mean_wakeup_gap": "175s"},
        },
        "momentum": {
            "enabled": True,
            "count": 2,
            "params": {"wake_up_freq": "37s"},
        },
        "adaptive_market_maker": {"enabled": True, "count": 1, "params": {}},
        "pov_execution": {
            "enabled": True,
            "count": 1,
            "params": {
                "direction": "BID",
                "quantity": 100000,
                "pov": 0.1,
                "freq": "1min",
                "trade": True,
            },
        },
    },
}

config = SimulationConfig(**config_dict)
t0 = time.time()
result = run_simulation(config, profile=ResultProfile.FULL)
elapsed = time.time() - t0
print(f"Simulation completed in {elapsed:.1f}s")

l1 = result.L1
if l1 is not None and not l1.empty:
    if "QuoteTime" in l1.columns:
        l1["QuoteTime"] = pd.to_datetime(l1["QuoteTime"])
        print(f"L1 rows: {len(l1)}")
        print(f"Time range: {l1['QuoteTime'].min()} to {l1['QuoteTime'].max()}")
        duration = l1["QuoteTime"].max() - l1["QuoteTime"].min()
        print(f"Duration: {duration}")
    else:
        print(f"L1 rows: {len(l1)}, columns: {list(l1.columns)}")
else:
    print("No L1 data")
