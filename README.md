# abides-ui

Interactive market simulation dashboard powered by [ABIDES](https://github.com/GabrieleDiCorato/abides-hasufel).

Configure agent-based market simulations, run them locally, and visualize price dynamics — all from a Streamlit web interface.

## Quick Start

```bash
# Install dependencies
uv sync

# Launch the dashboard
streamlit run src/abides_ui/app.py
```

The app opens at [http://localhost:8501](http://localhost:8501).

## Features

- **Preset configurations** — Quick, RMSC-04, and Liquid Market presets for instant simulation
- **Full parameter control** — ticker, date, oracle parameters, agent composition
- **Price visualization** — interactive Plotly chart of L1 best bid/ask/mid price series
- **Summary metrics** — mid price, VWAP, bid-ask spread, volume, wall-clock time
- **Agent P&L** — aggregated and per-agent profit & loss breakdown

## Deploy to Streamlit Cloud

1. Push this repo to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Point to `src/abides_ui/app.py` as the main file
4. Deploy

> **Note:** Streamlit Cloud has ~1 GB RAM. Use the **Quick** preset (≈126 agents) for cloud deployments. Larger configurations (1000+ agents) run best locally.
