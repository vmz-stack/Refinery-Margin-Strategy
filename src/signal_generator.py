"""
signal_generator.py
Shared logic for the refinery margin statistical arbitrage project.

Source: Aspen HYSYS V15 CDU simulation, ExxonMobil WTI Light assay
        (EMTEC Reference WTIL220Y, October 2020)

METHODOLOGY - Partial Product Spread:
Only naphtha and diesel are priced, since they map to liquid daily
futures (RBOB, Heating Oil). Kerosene, AGO and residue have no
equivalent liquid series and are excluded rather than estimated with
an assumed discount. Crude cost is therefore scaled to the fraction
of the barrel actually being priced, so the spread measures margin on
the modelled output only.
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize


# ============================================================
# HYSYS-DERIVED CONSTANTS
# Basis: 9,336 kg/h crude feed
# ============================================================

CRUDE_FEED_KGH = 9336.0

YIELD_NAPHTHA  = 319.7  / CRUDE_FEED_KGH   # 0.0342 - priced via RBOB
YIELD_KEROSENE = 1096.0 / CRUDE_FEED_KGH   # 0.1174 - excluded
YIELD_DIESEL   = 1142.0 / CRUDE_FEED_KGH   # 0.1223 - priced via Heating Oil
YIELD_AGO      = 1172.0 / CRUDE_FEED_KGH   # 0.1255 - excluded
YIELD_RESIDUE  = 5353.0 / CRUDE_FEED_KGH   # 0.5733 - excluded

UTILITY_COST_PER_BBL  = 0.112              # $/bbl, HYSYS Activated Economics
GALLONS_PER_BARREL    = 42
PRICED_YIELD_FRACTION = YIELD_NAPHTHA + YIELD_DIESEL   # 0.1565


# ============================================================
# SPREAD CONSTRUCTION
# ============================================================

def compute_hysys_margin(wti, rbob, heating_oil):
    """
    HYSYS-weighted partial product spread, $/bbl.

    Crude cost is scaled by PRICED_YIELD_FRACTION rather than charging a
    full barrel against a partial output - see module docstring.
    """
    rbob_bbl = rbob * GALLONS_PER_BARREL
    ho_bbl   = heating_oil * GALLONS_PER_BARREL
    return (
          YIELD_NAPHTHA * rbob_bbl
        + YIELD_DIESEL  * ho_bbl
        - PRICED_YIELD_FRACTION * wti
        - UTILITY_COST_PER_BBL
    )


def compute_generic_321_spread(wti, rbob, heating_oil):
    """Conventional 3:2:1 crack spread, $/bbl. Benchmark only."""
    rbob_bbl = rbob * GALLONS_PER_BARREL
    ho_bbl   = heating_oil * GALLONS_PER_BARREL
    return (2/3) * rbob_bbl + (1/3) * ho_bbl - wti


def compute_zscore(series, lookback=126):
    """Rolling z-score. Strictly backward-looking at every point."""
    mean = series.rolling(lookback).mean()
    std  = series.rolling(lookback).std()
    return (series - mean) / std


# ============================================================
# SIGNAL GENERATION
# ============================================================

def generate_signals(zscore, entry_threshold=1.75, exit_threshold=0.5):
    """
    Long when z < -entry, short when z > +entry.

    Positions close once the spread has reverted to within exit_threshold
    of the mean, rather than waiting for full reversion to zero. With a
    ~20-day half-life, waiting for z = 0 holds positions for months and
    produces too few trades to evaluate.

    Returns a Series of 1 (long), -1 (short), 0 (flat).
    """
    signals  = pd.Series(0, index=zscore.index)
    position = 0
    for i in range(len(zscore)):
        z = zscore.iloc[i]
        if np.isnan(z):
            signals.iloc[i] = 0
            continue
        if position == 0:
            if z < -entry_threshold:
                position = 1
            elif z > entry_threshold:
                position = -1
        elif position == 1 and z >= -exit_threshold:
            position = 0
        elif position == -1 and z <= exit_threshold:
            position = 0
        signals.iloc[i] = position
    return signals


def apply_holding_period(signals, min_hold=5):
    """
    Operational inertia friction term.

    A refinery cannot change its yield slate instantaneously - heater
    duty, draw rates and stripper steam take days to stabilise. Signal
    changes within min_hold days of the previous change are suppressed.
    """
    held        = signals.copy()
    last_change = -min_hold
    prev        = 0
    for i in range(len(signals)):
        if signals.iloc[i] != prev and (i - last_change) >= min_hold:
            held.iloc[i] = signals.iloc[i]
            last_change  = i
            prev         = signals.iloc[i]
        else:
            held.iloc[i] = prev
    return held


# ============================================================
# ORNSTEIN-UHLENBECK ESTIMATION
# ============================================================

def ou_neg_log_likelihood(params, X, dt=1.0):
    """Negative log-likelihood using the exact Gaussian transition density."""
    theta, mu, sigma = params
    if theta <= 0 or sigma <= 0:
        return 1e10
    n         = len(X) - 1
    X_t, X_t1 = X[:-1], X[1:]
    decay     = np.exp(-theta * dt)
    exp_val   = X_t * decay + mu * (1 - decay)
    var       = (sigma**2 / (2 * theta)) * (1 - np.exp(-2 * theta * dt))
    if var <= 0:
        return 1e10
    return -((-n / 2) * np.log(2 * np.pi * var)
             - np.sum((X_t1 - exp_val)**2) / (2 * var))


def fit_ou_process(series):
    """
    Fit dX = theta(mu - X)dt + sigma*dW by maximum likelihood.

    Returns theta, mu, sigma, half-life and the stationary standard
    deviation sigma/sqrt(2*theta).
    """
    X = np.asarray(series, dtype=float)
    result = minimize(
        ou_neg_log_likelihood,
        x0=[0.1, X.mean(), X.std()],
        args=(X,),
        method='L-BFGS-B',
        bounds=[(1e-6, 10), (None, None), (1e-6, None)]
    )
    theta, mu, sigma = result.x
    return {
        'theta':          theta,
        'mu':             mu,
        'sigma':          sigma,
        'half_life':      np.log(2) / theta,
        'stationary_sd':  sigma / np.sqrt(2 * theta),
        'converged':      result.success
    }


# ============================================================
# BACKTESTING
# ============================================================

def compute_pnl(signals, spread, transaction_cost=0.05):
    """
    Daily PnL with a one-day signal lag.

    signals.shift(1) means a position established from day t-1's close
    earns day t's move - the strategy never trades on information that
    was not available at the time of the decision.
    """
    out = pd.DataFrame(index=signals.index)
    out['signal']       = signals
    out['pnl_gross']    = signals.shift(1) * spread.diff()
    out['trade']        = signals.diff().abs().clip(0, 1)
    out['pnl_net']      = out['pnl_gross'] - out['trade'] * transaction_cost
    out['equity_curve'] = out['pnl_net'].cumsum()
    return out


def compute_performance_metrics(pnl, trades=None, n_days=None):
    """Standard performance metrics. Sharpe annualised at sqrt(252)."""
    eq = pnl.cumsum()
    sd = pnl.std()
    m = {
        'total_return':   pnl.sum(),
        'sharpe_ratio':   (pnl.mean() / sd) * np.sqrt(252) if sd > 0 else 0.0,
        'annualised_vol': sd * np.sqrt(252),
        'max_drawdown':   (eq - eq.cummax()).min(),
        'win_rate':       (pnl > 0).mean()
    }
    if trades is not None:
        m['num_trades'] = int(trades.sum() / 2)
        if n_days:
            m['turnover'] = trades.sum() / n_days
    return m
