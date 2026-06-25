"""
signal_generator.py
Reusable signal generation and backtesting functions for the
physically-grounded crack spread trading strategy.

Source: Aspen HYSYS CDU simulation, WTI Light crude assay
        ExxonMobil EMTEC Reference WTIL220Y (October 2020)
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize


# ============================================================
# HYSYS-DERIVED CONSTANTS
# ============================================================

YIELD_NAPHTHA        = 319.7  / 9336   # 0.0342 — maps to RBOB (RB=F)
YIELD_KEROSENE       = 1096.0 / 9336   # 0.1174 — jet fuel
YIELD_DIESEL         = 1142.0 / 9336   # 0.1223 — maps to Heating Oil (HO=F)
YIELD_AGO            = 1172.0 / 9336   # 0.1255 — atmospheric gas oil
YIELD_RESIDUE        = 5353.0 / 9336   # 0.5733 — atmospheric residue
UTILITY_COST_PER_BBL = 0.112           # USD/bbl (HYSYS Activated Economics)
GALLONS_PER_BARREL   = 42


def compute_hysys_margin(wti, rbob, heating_oil):
    """
    Compute the HYSYS-weighted refinery margin series.

    Parameters
    ----------
    wti         : pd.Series — WTI crude price in $/bbl
    rbob        : pd.Series — RBOB gasoline price in $/gallon
    heating_oil : pd.Series — Heating oil price in $/gallon

    Returns
    -------
    pd.Series — Refinery margin in $/bbl
    """
    rbob_bbl = rbob * GALLONS_PER_BARREL
    ho_bbl   = heating_oil * GALLONS_PER_BARREL
    margin = (
          YIELD_NAPHTHA * rbob_bbl
        + YIELD_DIESEL  * ho_bbl
        - wti
        - UTILITY_COST_PER_BBL
    )
    return margin


def compute_generic_321_spread(wti, rbob, heating_oil):
    """
    Compute the generic 3:2:1 crack spread for comparison.

    Parameters
    ----------
    wti         : pd.Series — WTI crude price in $/bbl
    rbob        : pd.Series — RBOB gasoline price in $/gallon
    heating_oil : pd.Series — Heating oil price in $/gallon

    Returns
    -------
    pd.Series — 3:2:1 crack spread in $/bbl
    """
    rbob_bbl = rbob * GALLONS_PER_BARREL
    ho_bbl   = heating_oil * GALLONS_PER_BARREL
    return (2/3) * rbob_bbl + (1/3) * ho_bbl - wti


def compute_zscore(series, lookback=252):
    """
    Compute rolling z-score.

    Parameters
    ----------
    series   : pd.Series
    lookback : int — rolling window in days (default 252 = 1 year)

    Returns
    -------
    pd.Series — z-score
    """
    mean = series.rolling(lookback).mean()
    std  = series.rolling(lookback).std()
    return (series - mean) / std


def generate_signals(zscore, entry_threshold=1.5, exit_threshold=0.0):
    """
    Generate trading signals from z-score.

    Long  when z < -entry_threshold
    Short when z >  entry_threshold
    Exit  when |z| < exit_threshold

    Parameters
    ----------
    zscore          : pd.Series
    entry_threshold : float (default 1.5)
    exit_threshold  : float (default 0.0)

    Returns
    -------
    pd.Series — signals: 1 (long), -1 (short), 0 (flat)
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
        elif position == 1:
            if z >= exit_threshold:
                position = 0
        elif position == -1:
            if z <= -exit_threshold:
                position = 0
        signals.iloc[i] = position
    return signals


def apply_holding_period(signals, min_hold=5):
    """
    Apply operational inertia friction term.

    Enforces a minimum holding period between signal changes,
    derived from HYSYS process engineering constraints
    (refinery yield slate cannot be changed instantaneously).

    Parameters
    ----------
    signals  : pd.Series — raw signals (1, -1, 0)
    min_hold : int — minimum days between signal changes (default 5)

    Returns
    -------
    pd.Series — filtered signals
    """
    held             = signals.copy()
    last_change_idx  = -min_hold
    prev_signal      = 0
    for i in range(len(signals)):
        if signals.iloc[i] != prev_signal:
            if (i - last_change_idx) >= min_hold:
                held.iloc[i]    = signals.iloc[i]
                last_change_idx = i
                prev_signal     = signals.iloc[i]
            else:
                held.iloc[i] = prev_signal
        else:
            held.iloc[i] = prev_signal
    return held


def ou_neg_log_likelihood(params, X, dt=1.0):
    """Negative log-likelihood for OU process (for MLE fitting)."""
    theta, mu, sigma = params
    if theta <= 0 or sigma <= 0:
        return 1e10
    n        = len(X) - 1
    X_t      = X[:-1]
    X_t1     = X[1:]
    exp_decay = np.exp(-theta * dt)
    exp_val   = X_t * exp_decay + mu * (1 - exp_decay)
    var       = (sigma**2 / (2 * theta)) * (1 - np.exp(-2 * theta * dt))
    if var <= 0:
        return 1e10
    ll = (-n / 2) * np.log(2 * np.pi * var) \
         - np.sum((X_t1 - exp_val)**2) / (2 * var)
    return -ll


def fit_ou_process(series):
    """
    Fit Ornstein-Uhlenbeck process to a time series using MLE.

    Parameters
    ----------
    series : pd.Series or np.ndarray

    Returns
    -------
    dict with keys: theta, mu, sigma, half_life
    """
    X  = np.array(series)
    x0 = [0.1, X.mean(), X.std()]
    result = minimize(
        ou_neg_log_likelihood,
        x0=x0,
        args=(X,),
        method='L-BFGS-B',
        bounds=[(1e-6, 10), (None, None), (1e-6, None)]
    )
    theta, mu, sigma = result.x
    return {
        'theta':     theta,
        'mu':        mu,
        'sigma':     sigma,
        'half_life': np.log(2) / theta,
        'converged': result.success
    }


def compute_pnl(signals, margin_series, transaction_cost=0.05):
    """
    Compute daily PnL and equity curve.

    Parameters
    ----------
    signals          : pd.Series — position signals (1, -1, 0)
    margin_series    : pd.Series — margin in $/bbl
    transaction_cost : float — cost per trade in $/bbl (default 0.05)

    Returns
    -------
    pd.DataFrame with columns: pnl_gross, pnl_net, equity_curve
    """
    result              = pd.DataFrame(index=signals.index)
    result['signal']    = signals
    result['margin']    = margin_series
    result['margin_chg'] = margin_series.diff()
    result['pnl_gross'] = signals.shift(1) * result['margin_chg']
    result['trade_flag'] = signals.diff().abs().clip(0, 1)
    result['pnl_net']   = result['pnl_gross'] - result['trade_flag'] * transaction_cost
    result['equity_curve'] = result['pnl_net'].cumsum()
    return result


def compute_performance_metrics(pnl_series, equity_curve):
    """
    Compute standard performance metrics.

    Parameters
    ----------
    pnl_series    : pd.Series — daily net PnL
    equity_curve  : pd.Series — cumulative PnL

    Returns
    -------
    dict of performance metrics
    """
    daily_mean   = pnl_series.mean()
    daily_std    = pnl_series.std()
    sharpe       = (daily_mean / daily_std) * np.sqrt(252) if daily_std > 0 else 0
    max_drawdown = (equity_curve - equity_curve.cummax()).min()
    win_rate     = (pnl_series > 0).mean()
    return {
        'total_return':  pnl_series.sum(),
        'sharpe_ratio':  sharpe,
        'max_drawdown':  max_drawdown,
        'win_rate':      win_rate,
        'daily_mean':    daily_mean,
        'daily_std':     daily_std
    }
