# Physically-Grounded Crack Spread Trading Strategy

> A mean-reversion statistical arbitrage strategy on refinery product spreads, where the tradeable spread weighting is derived from an Aspen HYSYS atmospheric crude distillation simulation rather than the generic 3:2:1 textbook ratio. Benchmarked out-of-sample against the standard 3:2:1 crack spread.

---

## The Differentiator

Most crack spread models use this:

```python
Crack Spread = (2/3 × Gasoline + 1/3 × Heating Oil) − Crude
```

This project uses this instead:

```python
Spread = (yield_naphtha × RBOB × 42) + (yield_diesel × HO × 42) − (priced_yield_fraction × WTI) − utility_cost_per_bbl
```

Where `yield_naphtha = 0.0342` and `yield_diesel = 0.1223` come directly from a converged Aspen HYSYS atmospheric CDU simulation of a real WTI Light crude assay (ExxonMobil EMTEC, Reference WTIL220Y, 2020) — not assumed from a textbook. The utility cost per barrel ($0.112/bbl) comes from the HYSYS Activated Economics module.

This gives the strategy a **physical basis**: the spread mean-reverts because refinery economics are anchored to real process thermodynamics and capital constraints, not because of a statistical artefact. The strategy is benchmarked out-of-sample against the generic 3:2:1 spread to test whether this physically-derived weighting actually improves risk-adjusted performance — not just that it is conceptually interesting.

---

## Methodology Note — Partial Product Spread, Not Full Refinery Margin

The HYSYS simulation produces a full product slate from the WTI Light crude assay:

| Product | Yield % | Liquid daily futures available? |
|---------|---------|----------------------------------|
| Naphtha  | 3.4%  | Yes — RBOB (`RB=F`) |
| Kerosene | 11.7% | No |
| Diesel   | 12.2% | Yes — Heating Oil (`HO=F`) |
| AGO      | 12.6% | No |
| Residue  | 57.3% | No |

Kerosene, AGO, and residue have no equivalent liquid, exchange-traded daily futures series on Yahoo Finance. Rather than invent a discount-to-WTI assumption to price them synthetically — which would introduce an unverified number and undermine the real-data premise of this project — **this strategy deliberately prices only the naphtha and diesel revenue streams**, which together represent 15.65% of the barrel.

To keep the economics internally consistent, the crude cost charged in the spread formula is scaled proportionally to this priced fraction (`priced_yield_fraction = 0.1565`), not the full barrel price. This avoids subtracting full crude cost while only crediting a fraction of the output — the original flaw in an earlier version of this formula, caught during mentor review (see Acknowledgements).

All seven HYSYS product streams remain documented in `hysys/yield_output.csv` as evidence of the full simulation — only the tradeable subset is used in the pricing formula.

---

## Project Structure

---

## Part 1 — HYSYS Process Simulation

### Flowsheet Topology

An atmospheric crude distillation unit (CDU) was built from scratch in **Aspen HYSYS V15** using the Peng-Robinson equation of state and a manually characterised WTI Light crude assay sourced from ExxonMobil's published assay library.

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
| Software | Aspen HYSYS V15 |
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

Utility cost per barrel derived as: total utility cost per hour ($8.29/h) ÷ crude throughput in bbl/h (74.3 bbl/h at 790.2 kg/m³ density, 6.2898 bbl/m³). Full export available in `hysys/hysys_economics.xlsx`.

### HYSYS-Derived Constants (single source of truth: `src/signal_generator.py`)

```python
yield_naphtha         = 319.7  / 9336   # 0.0342  → priced, maps to RBOB (RB=F)
yield_kerosene        = 1096.0 / 9336   # 0.1174  → excluded, no liquid futures proxy
yield_diesel          = 1142.0 / 9336   # 0.1223  → priced, maps to Heating Oil (HO=F)
yield_ago             = 1172.0 / 9336   # 0.1255  → excluded, no liquid futures proxy
yield_residue         = 5353.0 / 9336   # 0.5733  → excluded, no liquid futures proxy
utility_cost_per_bbl  = 0.112           # USD/bbl
priced_yield_fraction = yield_naphtha + yield_diesel   # 0.1565
```

---

## Part 2 — Quantitative Strategy

### Data Sources

| Instrument | Ticker | Unit | Role |
|------------|--------|------|------|
| WTI Crude Oil | `CL=F` | $/bbl | Feedstock cost |
| RBOB Gasoline | `RB=F` | $/gallon | Naphtha proxy (priced) |
| Heating Oil | `HO=F` | $/gallon | Diesel proxy (priced) |

5-year daily data, January 2019 – January 2024, via `yfinance`.

### The Spread Formula

```python
spread = (yield_naphtha * RBOB * 42
        + yield_diesel  * HO   * 42
        - priced_yield_fraction * WTI
        - utility_cost_per_bbl)
```

RBOB and Heating Oil are quoted $/gallon; ×42 converts to $/bbl to match WTI.

### Train / Test Split

A chronological 70/30 split is used. **All parameter selection — stationarity tests, OU process fitting, and entry threshold selection — is performed on the training set only.** The test set is held out completely and used solely to report final out-of-sample performance.

### Statistical Framework

**Stationarity validation (train set):**

| Test | Null Hypothesis | Desired Result |
|------|----------------|----------------|
| ADF (Augmented Dickey-Fuller) | Unit root exists (non-stationary) | p-value < 0.05 → reject H₀ |
| KPSS | Series is stationary | p-value > 0.05 → fail to reject H₀ |

**Ornstein-Uhlenbeck process fit (MLE, train set only):**

| Parameter | Description |
|-----------|-------------|
| θ (theta) | Mean reversion speed (per day) |
| μ (mu) | Long-run equilibrium spread ($/bbl) |
| σ (sigma) | Volatility ($/bbl/day⁰·⁵) |
| Half-life | ln(2)/θ — practical trading horizon in days |

Fitted parameters are fixed after Notebook 3 and applied unchanged to the test set — never re-fitted on out-of-sample data.

**Entry threshold selection (train set only):**

A sensitivity sweep across thresholds (0.5σ–2.5σ) is run on train data only, selecting the threshold with the best in-sample Sharpe ratio. This threshold is then fixed and applied to the test set without modification.

### Trading Signal

```python
exit_threshold = 0.0   # exit when spread reverts to mean
# Long  when z < −entry_threshold: spread compressed, buy
# Short when z > +entry_threshold: spread wide, sell
```

### Look-Ahead Bias Handling

All PnL is computed with the signal lagged by one trading day (`signal.shift(1)`): a position entered on day *t* is based on the z-score computed from the closing price on day *t−1*, and the trade is assumed executed at day *t*'s close. **Trades are entered the day after the close used to compute the signal** — the strategy never acts on information not yet available at the time of the decision.

### Operational Inertia Friction Term

A refinery cannot instantly change its yield slate — feed heater temperatures, column draw stages, and side stripper steam rates require days of operational adjustment. A **minimum 5-day holding period** is enforced between signal changes, derived directly from the HYSYS process simulation. This is the key feature distinguishing this backtest from a generic statistical arbitrage model.

```python
MIN_HOLDING_DAYS = 5   # derived from HYSYS process engineering constraints
```

### Transaction Cost Assumption

**$0.05/bbl per trade.** NYMEX RBOB and Heating Oil futures contracts are sized at 42,000 gallons (1,000 bbl) per contract. Typical bid/ask spreads on front-month RBOB and HO run roughly $0.0005–$0.001/gallon (~$0.02–$0.04/bbl-equivalent) in normal liquidity; WTI futures (CL) typically show a one-tick ($0.01/bbl) spread. Combining the round-trip cost of establishing offsetting positions across three legs (crude + two product legs) plus modest execution slippage, **$0.05/bbl is a deliberately conservative estimate** intended to avoid overstating profitability. Exchange/clearing fees (~$1–2/contract, ~$0.001–0.002/bbl) and margin financing costs are not separately modelled — immaterial at this scale.

### Benchmark

The strategy is compared against the **generic 3:2:1 crack spread**, traded with identical mechanics (same z-score lookback, same entry threshold, same holding period, same transaction cost) to isolate the effect of the HYSYS-derived weighting itself, not differences in trading logic.

```python
crack_321 = (2/3) * RBOB * 42 + (1/3) * HO * 42 - WTI
```

---

## Results

*Generated by running all 4 notebooks in sequence — paste output from Notebook 4's final cell here.*

| Period | Strategy | Total Return ($/bbl) | Sharpe Ratio | Annualised Vol ($/bbl) | Max Drawdown ($/bbl) | Win Rate | Num Trades | Turnover |
|--------|----------|----------------------|--------------|-------------------------|------------------------|----------|------------|----------|
| Train (in-sample) | HYSYS partial spread | 6.29 | 0.42 | 6.06 | -5.79 | 30.2% | 5 | 0.0175 |
| Train (in-sample) | 3:2:1 benchmark | -38.89 | -0.57 | 27.52 | -70.83 | 24.8% | 0 | 0.0016 |
| Test (out-of-sample) | HYSYS partial spread | 4.27 | 0.89 | 3.2 | -2.11 | 18.8% | 2 | 0.0106 |
| Test (out-of-sample) | 3:2:1 benchmark | 44.21 | 0.89 | 32.96 | -23.91 | 37.3% | 3 | 0.0159 |

**Key OU parameters (train set):**

| Parameter | Value |
|-----------|-------|
| θ (mean reversion speed) | 0.0321 |
| μ (long-run mean, $/bbl) | 3.0897 |
| σ (volatility) | 0.4479 |
| Half-life (trading days) | 21.6 |
| Selected entry threshold | True |

---

## Setup

```bash
pip install -r requirements.txt
```

Run notebooks in order from inside the `notebooks/` folder:

1. **`01_data_pipeline.ipynb`** — pulls price data from Yahoo Finance
2. **`02_spread_construction.ipynb`** — builds the HYSYS-weighted partial spread + 3:2:1 benchmark
3. **`03_stationarity_ou_fit.ipynb`** — train/test split, stationarity tests, OU fit, threshold selection (train only)
4. **`04_backtest.ipynb`** — applies fixed parameters to full series, reports train vs test, HYSYS vs benchmark

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
| Aspen HYSYS V15 | Atmospheric CDU process simulation, yield extraction, economics |
| Python 3.x | Strategy implementation |
| pandas / numpy | Data manipulation and numerical computing |
| statsmodels | ADF/KPSS stationarity tests |
| scipy | OU parameter estimation via Maximum Likelihood |
| yfinance | Commodity futures price data |
| matplotlib | Visualisation |
| Jupyter Notebook (Anaconda) | Development environment |

---

## Acknowledgements

Methodology reviewed by a mentor with a quantitative finance background (AQR, Point72, Balyasny). Key revisions made in response to review: corrected the spread formula from a full-barrel-cost margin to an internally-consistent partial product spread (see Methodology Note above), added a chronological train/test split with all parameters fixed on training data only, added a benchmark comparison against the generic 3:2:1 spread, and added explicit documentation of look-ahead bias handling and transaction cost assumptions.

---

## Author

Chemical Engineering student, University of Nottingham (entering Year 3). Building a quant finance portfolio that combines process engineering domain knowledge with systematic trading methodology, targeting research and trading roles at energy-focused systematic funds.

Application cycle: Autumn 2026 — Citadel, Optiver, Jane Street, G-Research, Qube/Man Group, Winton.
