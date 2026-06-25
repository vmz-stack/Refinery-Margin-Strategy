# Physically-Grounded Crack Spread Trading Strategy

> A mean-reversion statistical arbitrage strategy on refinery crack spreads, where product yield weights are derived from an Aspen HYSYS atmospheric crude distillation simulation rather than the generic 3:2:1 textbook ratio.

---

## The Differentiator

Most crack spread models use this:

```python
Crack Spread = (2/3 × Gasoline + 1/3 × Heating Oil) − Crude
```

This project uses this instead:

```python
Margin = (yield_naphtha × RBOB × 42) + (yield_diesel × HO × 42) − WTI − utility_cost_per_bbl
```

Where `yield_naphtha = 0.0342` and `yield_diesel = 0.1223` come directly from a converged Aspen HYSYS atmospheric CDU simulation of a real WTI Light crude assay (ExxonMobil EMTEC, Reference WTIL220Y, 2020) — not assumed from a textbook. The utility cost per barrel ($0.112/bbl) comes from the HYSYS Activated Economics module.

This gives the strategy a **physical basis**: the spread mean-reverts because refinery economics are anchored to real process thermodynamics and capital constraints, not because of a statistical artefact. No other candidate on a quant finance application pile has a CDU simulation behind their crack spread model.

---

## Project Structure

---

## Part 1 — HYSYS Process Simulation

### Flowsheet Topology

An atmospheric crude distillation unit (CDU) was built from scratch in Aspen HYSYS V11 using the Peng-Robinson equation of state and a manually characterised WTI Light crude assay sourced from ExxonMobil's published assay library.

### Crude Assay

| Property | Value | Source |
|----------|-------|--------|
| Crude grade | WTI Light | ExxonMobil EMTEC WTIL220Y |
| API Gravity | 47.5 | ExxonMobil published assay |
| Specific Gravity (15°C) | 0.7902 g/cc | ExxonMobil published assay |
| Sulfur content | 0.05 wt% | ExxonMobil published assay |
| Watson UOPK | 12.25 | ExxonMobil published assay |
| Viscosity @ 40°C | 1.72 cP | ExxonMobil published assay |

TBP distillation curve entered manually from the published assay (8 atmospheric cut points, 65°C–370°C, mass basis). Light ends (C1–C5) entered from published assay speciation data.

### Key Simulation Parameters

| Parameter | Value |
|-----------|-------|
| Fluid package | Peng-Robinson |
| Feed conditions | 25°C, 200 kPa, 10,000 kg/h |
| Column stages | 28 (top-down numbering) |
| Condenser | Partial |
| Bottom stripping steam | 250°C, 250 kPa, 250 kg/h |
| Kerosene side stripper | Reboiled, draw stage 9, return stage 8 |
| Diesel side stripper | Steam stripped, draw stage 17, return stage 16 |
| AGO side stripper | Steam stripped, draw stage 22, return stage 21 |
| Convergence method | Modified HYSIM Inside-Out, damping factor 0.1 |
| Active column specs | Reflux ratio = 2.0, Condenser T = 40°C, 3× side draw flows |

### HYSYS Economics

| Item | Value |
|------|-------|
| Total Capital Cost | $3,625,743 |
| Total Utility Cost/year | $72,683 |
| Electricity | 75.56 kW ($5.856/h) |
| Cooling Water | 0.0203 MMGAL/h ($2.436/h) |
| **Utility cost per barrel** | **$0.112/bbl** |

Utility cost per barrel derived as: total utility cost per hour ($8.29/h) ÷ crude throughput in bbl/h (74.3 bbl/h at 790.2 kg/m³ density, 6.2898 bbl/m³).

### HYSYS-Derived Yield Fractions (direct Python inputs)

```python
# Basis: crude feed only (9,336 kg/h, excluding steam inputs)
yield_offgas         = 268.1  / 9336   # 0.0287
yield_naphtha        = 319.7  / 9336   # 0.0342  → maps to RBOB (RB=F)
yield_kerosene       = 1096.0 / 9336   # 0.1174  → jet fuel (informational)
yield_diesel         = 1142.0 / 9336   # 0.1223  → maps to Heating Oil (HO=F)
yield_ago            = 1172.0 / 9336   # 0.1255  → atmospheric gas oil
yield_residue        = 5353.0 / 9336   # 0.5733  → atmospheric residue
utility_cost_per_bbl = 0.112           # USD/bbl (HYSYS Activated Economics)
```

> **Note:** Naphtha yield (3.4%) reflects a conservative column operating point (reflux ratio 2.0, condenser temperature 40°C). The column was converged with side draw flow specs rather than overhead distillate rate specs — a deliberate choice to achieve numerical convergence, with yield fractions reported from the converged solution.

---

## Part 2 — Quantitative Strategy

### Data Sources

| Instrument | Ticker | Unit | Role |
|------------|--------|------|------|
| WTI Crude Oil | `CL=F` | $/bbl | Feedstock cost |
| RBOB Gasoline | `RB=F` | $/gallon | Naphtha/gasoline proxy |
| Heating Oil | `HO=F` | $/gallon | Diesel proxy |

Data sourced via `yfinance`, January 2019 – January 2024 (5-year daily).

### The Crack Spread Formula

```python
# Unit conversion: RBOB and HO quoted $/gallon → ×42 converts to $/bbl
margin = (yield_naphtha * RBOB    * 42
        + yield_diesel  * HeatOil * 42
        - WTI
        - utility_cost_per_bbl)
```

Compare against the generic 3:2:1 spread — plotted in `02_spread_construction.ipynb` — to illustrate the differentiator visually.

### Statistical Framework

**Step 1 — Stationarity validation:**

| Test | Null Hypothesis | Desired Result |
|------|----------------|----------------|
| ADF (Augmented Dickey-Fuller) | Unit root exists (non-stationary) | p-value < 0.05 → reject H₀ |
| KPSS | Series is stationary | p-value > 0.05 → fail to reject H₀ |

Both tests required to confirm mean reversion is a real, persistent property of the spread.

**Step 2 — Ornstein-Uhlenbeck process fit (MLE):**


| Parameter | Description |
|-----------|-------------|
| θ (theta) | Mean reversion speed (per day) |
| μ (mu) | Long-run equilibrium margin ($/bbl) |
| σ (sigma) | Volatility ($/bbl/day⁰·⁵) |
| Half-life | ln(2)/θ — practical trading horizon in days |

**Step 3 — Z-score signal generation:**

```python
lookback        = 252   # 1 year rolling window
entry_threshold = 1.5   # standard deviations from mean
exit_threshold  = 0.0   # exit when spread reverts to mean

# Long  when z < −1.5: margin too compressed, buy the spread
# Short when z > +1.5: margin too wide, sell the spread
# Exit  when |z| < 0.0: spread has reverted
```

### Operational Inertia Friction Term

A refinery cannot instantly change its yield slate — feed heater temperatures, column draw stages, and side stripper steam rates require time to adjust. A **minimum holding period of 5 days** is enforced between signal changes in the backtest. This constraint is derived directly from the HYSYS process simulation and is the key feature distinguishing this backtest from a generic statistical arbitrage model.

```python
MIN_HOLDING_DAYS = 5   # derived from HYSYS process engineering constraints
```

### Backtest Parameters

| Parameter | Value |
|-----------|-------|
| Data period | Jan 2019 – Jan 2024 |
| Lookback window | 252 trading days |
| Entry threshold | ±1.5σ |
| Exit threshold | 0.0σ |
| Transaction cost | $0.05/bbl per trade |
| Minimum holding period | 5 days (operational inertia) |

### Performance Results

| Metric | Value |
|--------|-------|
| Sharpe Ratio | *run notebooks* |
| Total Return | *run notebooks* |
| Max Drawdown | *run notebooks* |
| Win Rate | *run notebooks* |
| OU Half-life | *run notebooks* |
| Number of Trades | *run notebooks* |

---

## Setup

### Install dependencies

```bash
pip install -r requirements.txt
```

### Run notebooks in order

```bash
cd notebooks
jupyter notebook
```

1. **`01_data_pipeline.ipynb`** — pulls WTI/RBOB/HeatOil daily closes from Yahoo Finance, saves `data/raw_prices.csv`
2. **`02_spread_construction.ipynb`** — constructs HYSYS-weighted margin series and 3:2:1 benchmark, saves `data/spread_data.csv`
3. **`03_stationarity_ou_fit.ipynb`** — ADF/KPSS stationarity tests, MLE OU parameter estimation, z-score generation, saves `data/spread_with_zscore.csv` and `data/ou_parameters.csv`
4. **`04_backtest.ipynb`** — signal generation, operational inertia filter, PnL calculation, performance metrics, sensitivity analysis, saves `data/backtest_results.csv`

---

## Data Sources & Citations

**Crude Assay:**
> ExxonMobil Technology & Engineering Company (EMTEC). *Crude Summary Report — WTI Light (Reference WTIL220Y).* Published October 23, 2020. Available at: https://corporate.exxonmobil.com/crude-oils/crude-trading/assays-available-for-download

**Refinery yield methodology:**
> Jechura, J. (2019). *Refinery Feedstocks & Products: Properties & Specifications.* CBEN 409 – Petroleum Refining, Colorado School of Mines. Available at: https://people.mines.edu/jjechura

**HYSYS simulation methodology:**
> AspenTech. (2014). *EHY101 Aspen HYSYS: Process Modeling — Customer Education Training Manual (Course EHY101.086.01).* AspenTech, Inc.

**Market data:**
> Yahoo Finance via `yfinance` Python library. Tickers: CL=F, RB=F, HO=F.

---

## Technical Stack

| Tool | Purpose |
|------|---------|
| Aspen HYSYS V15| Atmospheric CDU process simulation, yield extraction, economics |
| Python 3.x | Strategy implementation |
| pandas / numpy | Data manipulation and numerical computing |
| statsmodels | ADF/KPSS stationarity tests |
| scipy | OU parameter estimation via Maximum Likelihood |
| yfinance | Commodity futures price data |
| matplotlib | Visualisation |
| Jupyter Notebook (Anaconda) | Development environment |

---

## Author

Chemical Engineering student, University of Nottingham (entering Year 3).
Building a quant finance portfolio that combines process engineering domain knowledge with systematic trading methodology, targeting research and trading roles at energy-focused systematic funds.

Application cycle: Autumn 2026 — Citadel, Optiver, Jane Street, G-Research, Qube/Man Group, Winton.
