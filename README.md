# Does Process-Simulation-Derived Weighting Improve a Crack Spread Strategy?

An empirical test of whether product yield weights derived from an Aspen HYSYS
crude distillation simulation improve a crack spread mean-reversion strategy,
relative to the conventional 3:2:1 ratio.

**Conclusion: no.** The physically-derived weighting did not outperform the
convention, and the underlying spread shows no statistical support for mean
reversion in any subperiod tested. This is reported as a null result.

---

## The Research Question

Most crack spread models use a fixed 3:2:1 product weighting — three barrels of
crude against two of gasoline and one of distillate. It approximates a typical US
refinery's output, but nothing derives it; it persists because it is simple and
liquid to trade.

```
Crack Spread = (2/3 × RBOB × 42) + (1/3 × HO × 42) − WTI
```

A chemical engineer can calculate the real split instead. This project asks
whether doing so produces a better strategy.

```
Spread = (yield_naphtha × RBOB × 42)
       + (yield_diesel  × HO   × 42)
       − (priced_yield_fraction × WTI)
       − utility_cost_per_bbl
```

`yield_naphtha = 0.0342` and `yield_diesel = 0.1223` come from a converged Aspen
HYSYS V15 CDU simulation of the ExxonMobil WTI Light assay. The $0.112/bbl
operating cost comes from HYSYS Activated Economics.

---

## Results

**Data:** NYMEX WTI (`CL=F`), RBOB (`RB=F`), Heating Oil (`HO=F`), 2010–2024,
3,771 trading days. Chronological 70/30 split at 2020-07-02.

### Out-of-sample performance

| Period | Strategy | PnL ($/bbl) | Sharpe | Ann. vol | Max DD | Trades |
|---|---|---|---|---|---|---|
| Train | HYSYS partial spread | 5.90 | 0.33 | 1.78 | −2.80 | 37 |
| Train | 3:2:1 benchmark | 87.80 | 0.67 | 13.06 | −22.78 | 36 |
| **Test** | **HYSYS partial spread** | **0.51** | **0.03** | **4.52** | **−11.61** | **10** |
| **Test** | **3:2:1 benchmark** | **9.42** | **0.13** | **16.12** | **−39.96** | **12** |

Both out-of-sample Sharpes are indistinguishable from zero, on trade counts too
small to support inference either way. The HYSYS weighting underperformed the
convention in both periods.

### Stationarity

The spread was tested for mean reversion on the full training period and on four
subperiods, to check whether an initially ambiguous result was driven by
structural breaks around COVID and the 2022 distillate squeeze.

| Period | n | ADF p | KPSS p | Verdict |
|---|---|---|---|---|
| Full train 2010–20 | 2,639 | 0.0497 | 0.0100 | disagree |
| Pre-COVID 2010–19 | 2,388 | 0.0327 | 0.0100 | disagree |
| COVID 2020–21 | 505 | 0.7046 | 0.0100 | not stationary |
| Post-2022 | 753 | 0.2069 | 0.0100 | not stationary |
| Excl. 2020–21 | 3,141 | 0.0766 | 0.0100 | not stationary |

**KPSS rejects stationarity at p = 0.01 in every subperiod, including calm ones.**
The structural-break hypothesis does not survive: no regime supports mean
reversion.

### OU parameter instability

| Period | θ | Half-life | μ ($/bbl) |
|---|---|---|---|
| Pre-COVID 2010–19 | 0.0103 | 67.2 d | 3.45 |
| COVID 2020–21 | 0.2430 | 2.9 d | 2.36 |
| Post-2022 | 0.0187 | 37.0 d | 5.80 |
| Excl. 2020–21 | 0.0099 | 70.2 d | 4.01 |
| Full train | 0.0299 | 23.2 d | 3.22 |

Half-life varies by a factor of 23 and the estimated long-run mean moves from
$2.36 to $5.80/bbl. A genuine mean-reverting process has stable parameters. The
MLE converges in every case, but convergence is not validity — it is fitting
noise.

### Why the signal fails, arithmetically

From the full-train fit: stationary sd $1.124/bbl, σ = 0.2751, half-life 23.2 days.

| | |
|---|---|
| Expected move from a 1.75σ entry over one half-life | **$0.98/bbl** |
| Noise accumulated over the same 23 days (σ√t) | **$1.32/bbl** |

Noise exceeds the expected move. Transaction costs are not the binding
constraint — $0.10 round-trip against a $0.98 expected move is 10%. The
reversion is simply too slow relative to the volatility.

---

## A Bug That Invalidated Earlier Results

An earlier version of the data pipeline assigned column names by position:

```python
raw.columns = list(tickers.keys())   # WRONG
```

`yfinance` returns columns in **alphabetical order by ticker** (`CL=F`, `HO=F`,
`RB=F`), not in request order. Crude landed correctly by luck of the alphabet;
RBOB and Heating Oil were silently swapped.

| | Old (positional) | Correct (by ticker) |
|---|---|---|
| WTI | 71.991 | 71.991 |
| RBOB | 2.315 | 2.180 |
| HeatOil | 2.180 | 2.315 |

Every result produced before this fix was computed on mislabelled data. The
pipeline now selects columns explicitly by ticker and asserts on plausible price
levels so the error cannot recur:

```python
raw = pd.DataFrame({name: dl[ticker] for name, ticker in tickers.items()})
assert raw['WTI'].mean()  > 20    # $/bbl
assert raw['RBOB'].mean() < 10    # $/gal
```

---

## Methodology

### Partial product spread, not a full refinery margin

The simulation produces a full product slate, but only two cuts have liquid daily
futures proxies:

| Product | Yield | Liquid futures? |
|---|---|---|
| Naphtha | 3.4% | Yes — RBOB |
| Kerosene | 11.7% | No |
| Diesel | 12.2% | Yes — Heating Oil |
| AGO | 12.6% | No |
| Residue | 57.3% | No |

Kerosene, AGO and residue are excluded rather than priced with an assumed
discount to crude, which would insert an unverified number into a project whose
premise is real, sourced data. Crude cost is scaled to the priced fraction
(0.1566) rather than charging a full barrel against a partial output.

**A consequence worth stating:** at 3.4% naphtha against 12.2% diesel, the spread
is effectively `0.122 × HO − 0.157 × WTI` — close to a diesel crack with an
unusual crude weighting. The gasoline leg barely contributes. This follows from a
conservative column operating point (reflux ratio 2.0, fixed condenser
temperature) and plausibly explains part of the underperformance against 3:2:1,
which carries genuinely balanced product exposure.

### Train / test discipline

Stationarity tests, OU fitting and entry-threshold selection are performed on
training data only. Every parameter is frozen before the test set is touched and
never re-fitted.

### Look-ahead bias

PnL uses `signal.shift(1)`: a position established from day *t−1*'s close earns
day *t*'s move. Trades are entered the day after the close that generated the
signal. The rolling z-score window is strictly backward-looking.

### Operational inertia

A refinery cannot change its yield slate instantaneously — heater duty, draw
rates and stripper steam take days to stabilise. A five-day minimum holding
period is enforced between signal changes, derived from the process simulation
rather than fitted.

### Transaction costs

$0.05/bbl per trade. NYMEX RBOB and HO contracts are 42,000 gallons (1,000 bbl).
Front-month bid/ask runs roughly $0.0005–0.001/gal ($0.02–0.04/bbl equivalent);
CL is typically one tick ($0.01/bbl). Across three legs plus slippage, $0.05/bbl
is deliberately conservative.

---

## Part 1 — HYSYS Simulation

An atmospheric CDU built in **Aspen HYSYS V15** using Peng-Robinson and a manually
characterised assay.

| Property | Value |
|---|---|
| Crude grade | WTI Light (ExxonMobil EMTEC WTIL220Y) |
| API gravity | 47.5 |
| SG @ 15°C | 0.7902 |
| Sulfur | 0.05 wt% |
| Watson UOPK | 12.25 |

TBP curve entered manually — 8 atmospheric cut points, 65–370°C, mass basis.
Light ends (C1–C5) from published speciation data.

| Parameter | Value |
|---|---|
| Feed | 25°C, 200 kPa, 10,000 kg/h |
| Column | 28 stages, partial condenser |
| Bottom steam | 250°C, 250 kPa, 250 kg/h |
| Kerosene stripper | Reboiled, draw 9, return 8 |
| Diesel stripper | Steam stripped, draw 17, return 16 |
| AGO stripper | Steam stripped, draw 22, return 21 |
| Convergence | Modified HYSIM Inside-Out, damping 0.1 |
| Active specs | Reflux ratio 2.0, condenser T 40°C, 3 × side draw flows |

**Economics:** $8.29/h total utility cost over 74.3 bbl/h throughput →
**$0.112/bbl**. Full export in `hysys/hysys_economics.xlsx`.

---

## Limitations

- **RBOB is an imperfect naphtha proxy.** Naphtha is a blendstock and
  petrochemical feedstock; RBOB is finished gasoline blendstock, further down the
  value chain. The basis between them is not constant and is unmodelled.
- **The naphtha yield is low.** The assay supports roughly 32% naphtha on a TBP
  cut basis; the simulation produces 3.4% because of the conservative column
  specification. Tuning the draw specs toward assay yields would make the weights
  more representative.
- **82% of the barrel is unpriced.** The strategy is a partial spread, not a
  refinery margin.
- **A single train/test split.** Walk-forward validation over multiple
  out-of-sample windows would be more robust than one split.

---

## Repository

```
├── hysys/          simulation outputs, economics export, flowsheet screenshot
├── data/           generated by the notebooks
├── notebooks/      01 data → 02 spreads → 03 stationarity/OU → 04 backtest
├── src/            signal_generator.py — shared logic, single source of truth
└── requirements.txt
```

```bash
pip install -r requirements.txt
cd notebooks && jupyter notebook
```

Run in order.

---

## Sources

**Crude assay** — ExxonMobil Technology & Engineering Company. *Crude Summary
Report: WTI Light (WTIL220Y)*, 23 October 2020.
https://corporate.exxonmobil.com/crude-oils/crude-trading/assays-available-for-download

**Refining methodology** — Jechura, J. (2019). *Refinery Feedstocks & Products*.
CBEN 409, Colorado School of Mines. https://people.mines.edu/jjechura

**HYSYS methodology** — AspenTech (2014). *EHY101 Aspen HYSYS: Process Modeling*.

**Market data** — Yahoo Finance via `yfinance`.

---

## Stack

Aspen HYSYS V15 · Python (pandas, NumPy, SciPy, statsmodels) · Jupyter

---

## Revisions

The methodology changed materially over three iterations. Recording that here
rather than presenting only the final version, since the corrections are the
substantive part:

**Spread formulation.** The first version subtracted a full WTI barrel while
crediting only naphtha and diesel revenue — 15.66% of the output. That is not a
margin; it is a number without an economic interpretation. Crude cost is now
scaled to the priced yield fraction.

**Train/test discipline.** Stationarity tests, the OU fit and threshold selection
originally ran on the full sample, so reported performance was in-sample
throughout. A chronological 70/30 split was added, with every parameter frozen
before the test set is touched.

**Benchmark.** Without a comparison the result was uninterpretable — a Sharpe
means nothing in isolation. The conventional 3:2:1 spread is now traded under
identical mechanics, isolating the effect of the weighting itself.

**Data integrity.** A column-ordering bug swapped the RBOB and Heating Oil series
(see above), invalidating all results produced before it was found.

**Sample size.** The original 2019–2024 window produced two out-of-sample trades.
Extending to 2010–2024 and exiting at ±0.5σ rather than full reversion brought the
count to a level where the null result means something.

**Framing.** Presented initially as a performance claim; now stated as a research
question with an evidence-based negative answer.
