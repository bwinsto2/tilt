
import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional
import os
import re
import matplotlib.pyplot as plt

PRACTICE_COLS = ['center', 'surround', 'type', 'surr_type', 'surr_opacity']
SURROUND_ORDER = ['noss','poss','negs']

# ------------------------------
# Helpers
# ------------------------------
def _infer_block_column(df: pd.DataFrame) -> Optional[str]:
    for c in ['blocks.thisRepN', 'blocks.thisN']:
        if c in df.columns and df[c].notna().any():
            return c
    return None

def _extract_surround_from_label(df: pd.DataFrame) -> pd.Series:
    if 'trials.label' not in df.columns:
        raise ValueError("Missing required column 'trials.label'.")
    return df['trials.label'].astype(str).str.split('_').str[-1]

def _ensure_required_trial_cols(df: pd.DataFrame):
    missing = [c for c in ['trials.label','trials.intensity'] if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required column(s): {missing}")

def _last_k_mean(series: pd.Series, k: int) -> float:
    if series.empty:
        return float('nan')
    k_eff = min(k, len(series))
    return float(series.tail(k_eff).mean())

def _normalize_response_keys(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize response keys: convert 'z' -> 'left' and 'period' -> 'right'.
    This handles both old format (left/right) and new format (z/period).
    """
    d = df.copy()
    if 'resp.keys' in d.columns:
        d['resp.keys'] = d['resp.keys'].replace({'z': 'left', 'period': 'right'})
    return d

# ------------------------------
# PSEs from staircase data
# ------------------------------
def pse_last_k_per_block_per_condition(df: pd.DataFrame, k: int = 6) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    For each block + surround condition (noss/poss/negs):
      - keep original row order,
      - take the last k trials' 'trials.intensity' and average,
    Then average those per-block means across blocks to get one PSE per condition.

    Returns (per_block_table, collapsed_table).

    per_block_table columns:
      block_id, condition, n_trials_available, n_used, mean_last_k

    collapsed_table columns:
      condition, PSE, n_blocks_used
    """
    _ensure_required_trial_cols(df)
    d = df.dropna(subset=['trials.label','trials.intensity']).copy()
    d['surround'] = _extract_surround_from_label(d)

    block_col = _infer_block_column(df)
    if block_col is None:
        d['_block_id'] = 0
    else:
        d['_block_id'] = df[block_col]

    rows = []
    for bid, g_block in d.groupby('_block_id', dropna=False):
        g_block = g_block.sort_index()  # preserve run order
        for cond in SURROUND_ORDER:
            g = g_block[g_block['surround'] == cond]
            n_avail = int(g.shape[0])
            mean_last = _last_k_mean(g['trials.intensity'], k)
            rows.append({
                'block_id': bid if pd.notna(bid) else 'NA',
                'condition': cond,
                'n_trials_available': n_avail,
                'n_used': min(k, n_avail),
                'mean_last_k': mean_last
            })
    per_block = pd.DataFrame(rows)
    per_block['condition'] = pd.Categorical(per_block['condition'], categories=SURROUND_ORDER, ordered=True)
    per_block = per_block.sort_values(['block_id','condition']).reset_index(drop=True)

    coll = (per_block.groupby('condition', as_index=False)
            .agg(PSE=('mean_last_k','mean'),
                 n_blocks_used=('mean_last_k', lambda s: int(s.notna().sum()))))
    coll['condition'] = pd.Categorical(coll['condition'], categories=SURROUND_ORDER, ordered=True)
    coll = coll.sort_values('condition').reset_index(drop=True)
    return per_block, coll

# ------------------------------
# Stimuli from PSEs (practice_stims schema)
# ------------------------------
def make_stimuli_from_pse(
    pse_by_condition: Dict[str, float],
    step: float = 0.5,
    surround_mag: float = 15.0,
    reps_poss_negs: int = 1,
    reps_noss: int = 1,
    n_conditions: int = 5,
    extremes_double: bool = True,   # <-- NEW
) -> pd.DataFrame:
    for key in ['poss','negs','noss']:
        if key not in pse_by_condition:
            raise ValueError("pse_by_condition must include 'poss', 'negs', and 'noss'.")

    if n_conditions == 5:
        offsets = [('m2', -2*step), ('m1', -1*step), ('PSE', 0.0), ('p1', +1*step), ('p2', +2*step)]
    elif n_conditions == 7:
        if extremes_double:
            # m3/p3 jump is 2*step beyond m2/p2 → ±4*step
            offsets = [('m3', -4*step), ('m2', -2*step), ('m1', -1*step),
                       ('PSE', 0.0),
                       ('p1', +1*step), ('p2', +2*step), ('p3', +4*step)]
        else:
            offsets = [('m3', -3*step), ('m2', -2*step), ('m1', -1*step),
                       ('PSE', 0.0),
                       ('p1', +1*step), ('p2', +2*step), ('p3', +3*step)]
    else:
        raise ValueError('n_conditions must be 5 or 7')

    rows = []

    # poss: sweep around its PSE (can cross 0)
    pse = float(pse_by_condition['poss'])
    for tname, delta in offsets:
        level = pse + delta
        for _ in range(int(reps_poss_negs)):
            rows.append({'center': level, 'surround': +abs(surround_mag),
                         'type': tname, 'surr_type': 'poss', 'surr_opacity': 100})

    # negs: sweep around its PSE (can cross 0)
    pse = float(pse_by_condition['negs'])
    for tname, delta in offsets:
        level = pse + delta
        for _ in range(int(reps_poss_negs)):
            rows.append({'center': level, 'surround': -abs(surround_mag),
                         'type': tname, 'surr_type': 'negs', 'surr_opacity': 100})

    # noss: PSE fixed at 0 (your request)
    pse = 0.0
    for tname, delta in offsets:
        level = pse + delta
        for _ in range(int(reps_noss)):
            rows.append({'center': level, 'surround': 0,
                         'type': tname, 'surr_type': 'noss', 'surr_opacity': 0})

    out = pd.DataFrame(rows, columns=PRACTICE_COLS)

    # stable ordering
    type_order = {name:i for i, name in enumerate([lab for lab,_ in offsets])}
    surr_order = {'poss':0,'negs':1,'noss':2}
    out['__to'] = out['type'].map(type_order)
    out['__so'] = out['surr_type'].map(surr_order)
    out = out.sort_values(['__so','__to','center']).drop(columns=['__to','__so']).reset_index(drop=True)
    return out


# ------------------------------
# Wrapper: CSV -> stimuli DataFrame (+ optional save)
# ------------------------------
def build_trials_from_staircase(
    csv_path: str,
    k: int = 6,
    step: float = 0.5,
    surround_mag: float = 15.0,
    reps_poss_negs: int = 1,
    reps_noss: int = 1,
    out_csv: Optional[str] = None,
    n_conditions: int = 5
) -> Tuple[pd.DataFrame, Dict[str, float], pd.DataFrame, pd.DataFrame, Optional[str]]:
    df = pd.read_csv(csv_path)
    per_block, collapsed = pse_last_k_per_block_per_condition(df, k=k)
    pse_map = {row['condition']: float(row['PSE']) for _, row in collapsed.iterrows()}
    stim = make_stimuli_from_pse(pse_map, step=step, surround_mag=surround_mag,
                                 reps_poss_negs=reps_poss_negs, reps_noss=reps_noss,
                                 n_conditions=n_conditions)
    saved_path = None
    if out_csv:
        import os
        os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
        stim.to_csv(out_csv, index=False)
        saved_path = out_csv
    return stim, pse_map, per_block, collapsed, saved_path

# ------------------------------
# Variability across blocks (optional helper)
# ------------------------------
def summarize_pse_variability(per_block_df: pd.DataFrame) -> pd.DataFrame:
    try:
        from scipy.stats import t as tdist
        t_ppf = lambda p, df: float(tdist.ppf(p, df))
    except Exception:
        import numpy as np
        t_ppf = lambda p, df: 1.96
    g = per_block_df.dropna(subset=["mean_last_k"]).groupby("condition")["mean_last_k"]
    out = g.agg(n_blocks="count", mean="mean", sd="std").reset_index()
    import numpy as np
    out["sem"] = out["sd"] / np.sqrt(out["n_blocks"].clip(lower=1))
    out["ci95_lo"] = out.apply(
        lambda r: r["mean"] - t_ppf(0.975, int(r["n_blocks"] - 1)) * r["sem"] if r["n_blocks"] >= 2 else np.nan,
        axis=1
    )
    out["ci95_hi"] = out.apply(
        lambda r: r["mean"] + t_ppf(0.975, int(r["n_blocks"] - 1)) * r["sem"] if r["n_blocks"] >= 2 else np.nan,
        axis=1
    )
    return out

# ------------------------------
# MoCS analysis (phase 2) + values
# ------------------------------
def _clean_mocs_df(df: pd.DataFrame) -> pd.DataFrame:
    required = ['type', 'surr_type', 'resp.keys', 'center']
    for c in required:
        if c not in df.columns:
            raise ValueError(f"MoCS file missing required column: {c}")
    d = df.copy()
    d = _normalize_response_keys(d)  # Convert z/period to left/right
    valid_types = {'m3','m2','m1','PSE','p1','p2','p3'}
    d = d[d['type'].isin(valid_types)]
    d = d[d['resp.keys'].isin(['left','right'])]
    return d

def _collect_values_tuple(series: pd.Series):
    arr = pd.unique(series.dropna())
    try:
        arr = [float(x) for x in arr]
    except Exception:
        pass
    arr = sorted(arr)
    arr = [round(float(x), 3) for x in arr]
    return tuple(arr)

def analyze_mocs(df: pd.DataFrame) -> (pd.DataFrame, pd.DataFrame):
    """
    Compute left/right proportions by type for MoCS.
    Returns (combined, separate):
      combined: poss+negs lumped as 'with_surround', noss separate
      separate: poss, negs, noss kept distinct
    Columns: type, group/surr_type, n, n_left, n_right, p_left, p_right, values
    where 'values' is a tuple of the distinct center orientations actually used.
    """
    d = _clean_mocs_df(df)

    # Combined (lump poss+negs)
    d['group'] = np.where(d['surr_type'].isin(['poss','negs']), 'with_surround', 'noss')
    comb_counts = (d.groupby(['type','group'])['resp.keys']
                     .value_counts().rename('count').reset_index())
    comb_p = (comb_counts.pivot_table(index=['type','group'],
                                      columns='resp.keys', values='count',
                                      fill_value=0).reset_index())
    if 'left' not in comb_p.columns: comb_p['left'] = 0
    if 'right' not in comb_p.columns: comb_p['right'] = 0
    comb_p['n'] = comb_p['left'] + comb_p['right']
    comb_p['p_left'] = comb_p['left'] / comb_p['n'].where(comb_p['n']>0, 1)
    comb_p['p_right'] = comb_p['right'] / comb_p['n'].where(comb_p['n']>0, 1)

    vals_comb = (d.groupby(['type','group'])['center']
                   .apply(_collect_values_tuple).reset_index(name='values'))
    comb_out = comb_p.merge(vals_comb, on=['type','group'], how='left')
    comb_out = comb_out.rename(columns={'left':'n_left','right':'n_right'})
    comb_out = comb_out[['type','group','n','n_left','n_right','p_left','p_right','values']]\
                     .sort_values(['group','type']).reset_index(drop=True)

    # Separate (poss, negs, noss)
    sep_counts = (d.groupby(['type','surr_type'])['resp.keys']
                    .value_counts().rename('count').reset_index())
    sep_p = (sep_counts.pivot_table(index=['type','surr_type'],
                                    columns='resp.keys', values='count',
                                    fill_value=0).reset_index())
    if 'left' not in sep_p.columns: sep_p['left'] = 0
    if 'right' not in sep_p.columns: sep_p['right'] = 0
    sep_p['n'] = sep_p['left'] + sep_p['right']
    sep_p['p_left'] = sep_p['left'] / sep_p['n'].where(sep_p['n']>0, 1)
    sep_p['p_right'] = sep_p['right'] / sep_p['n'].where(sep_p['n']>0, 1)

    vals_sep = (d.groupby(['type','surr_type'])['center']
                  .apply(_collect_values_tuple).reset_index(name='values'))
    separate = sep_p.merge(vals_sep, on=['type','surr_type'], how='left')
    separate = separate.rename(columns={'left':'n_left','right':'n_right'})
    separate = separate[['type','surr_type','n','n_left','n_right','p_left','p_right','values']]\
                       .sort_values(['surr_type','type']).reset_index(drop=True)

    return comb_out, separate

def analyze_mocs_from_csv(path: str):
    df = pd.read_csv(path)
    return analyze_mocs(df)

# ------------------------------
# Analysis & plotting for fixed MOCS stimuli
# ------------------------------
def _clean_fixed_mocs_df(df: pd.DataFrame) -> pd.DataFrame:
    """Clean dataframe from fixed MOCS stimuli experiments."""
    required = ['center', 'surr_type', 'resp.keys']
    for c in required:
        if c not in df.columns:
            raise ValueError(f"Fixed MoCS file missing required column: {c}")
    d = df.copy()
    d = _normalize_response_keys(d)  # Convert z/period to left/right
    # Filter to valid responses only
    d = d[d['resp.keys'].isin(['left','right'])]
    # Filter to valid surround types
    d = d[d['surr_type'].isin(['poss','negs','noss'])]
    return d

def fixed_mocs_psychometric_tables(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """
    Build per-surround psychometric tables for fixed MOCS stimuli.
    Returns dict: {'poss': df, 'negs': df, 'noss': df} for those present.
    Each df has columns: center, n, n_left, n_right, p_left
    """
    d = _clean_fixed_mocs_df(df)
    out = {}
    for s in ['poss','negs','noss']:
        g = d[d['surr_type'] == s]
        if g.empty:
            continue
        tbl = (g.groupby('center')['resp.keys']
                 .value_counts().rename('count').reset_index())
        piv = (tbl.pivot_table(index='center', columns='resp.keys',
                               values='count', fill_value=0).reset_index())
        if 'left' not in piv.columns: piv['left'] = 0
        if 'right' not in piv.columns: piv['right'] = 0
        piv = piv.rename(columns={'left':'n_left','right':'n_right'})
        piv['n'] = piv['n_left'] + piv['n_right']
        piv['p_left'] = piv['n_left'] / piv['n'].where(piv['n']>0, 1)
        piv['p_right'] = piv['n_right'] / piv['n'].where(piv['n']>0, 1)
        out[s] = piv.sort_values('center').reset_index(drop=True)
    return out


def _find_p50_crossing(x, y):
    """
    Find the x-value where the psychometric curve crosses P=0.5.
    Uses linear interpolation between adjacent points.
    Returns None if no crossing found.
    """
    for i in range(len(y) - 1):
        if (y[i] <= 0.5 <= y[i+1]) or (y[i] >= 0.5 >= y[i+1]):
            if y[i+1] - y[i] != 0:
                x_cross = x[i] + (0.5 - y[i]) * (x[i+1] - x[i]) / (y[i+1] - y[i])
                return x_cross
    return None


def plot_fixed_mocs_psychometric(
    df: pd.DataFrame,
    output_dir: Optional[str] = None,
    fit: bool = True,
    model: str = "logistic2",
    subject: Optional[str] = None,
):
    """
    Plot empirical psychometric functions for fixed MOCS stimuli (poss, negs, noss).
    
    Parameters:
    -----------
    df : pd.DataFrame
        Dataframe with columns: center, surr_type, resp.keys
    output_dir : Optional[str]
        If provided, save plots to this directory
    fit : bool
        Whether to fit logistic curves
    model : str
        'logistic2' or 'logistic4'
    subject : Optional[str]
        Subject ID for plot titles
    
    Returns:
    --------
    dict mapping surround type to figure or file path
    """
    tables = fixed_mocs_psychometric_tables(df)
    results = {}

    for surr, tab in tables.items():
        fig = plt.figure()
        x = tab["center"].to_numpy()
        y = tab["p_right"].to_numpy()
        order = np.argsort(x)
        x, y = x[order], y[order]
        plt.plot(x, y, "o-")

        # Build title
        subj_part = f"Subject {subject}" if subject else "Subject unknown"
        title_txt = f"{subj_part} – {surr}"

        # Add vertical line at P(50) crossing
        p50_x = _find_p50_crossing(x, y)
        if p50_x is not None:
            plt.axvline(p50_x, linestyle=":", color='gray')
            title_txt += f" (P50={p50_x:.2f})"

        if fit and len(np.unique(x)) >= 3:
            try:
                fitres = fit_psychometric_logistic(tab, model=model)
                # Compute fit curve
                xgrid = np.linspace(np.min(x), np.max(x), 200)
                if model == "logistic2":
                    yhat = _logistic2(xgrid, fitres["x0"], max(fitres["s"], 1e-6))
                else:
                    yhat = _logistic4(
                        xgrid,
                        fitres["x0"],
                        max(fitres["s"], 1e-6),
                        float(fitres.get("gamma", 0.0)),
                        float(fitres.get("lambda", 0.0)),
                    )
                plt.plot(xgrid, yhat, "-", alpha=0.7)
            except Exception as e:
                title_txt += f"\n(fit failed: {e})"

        plt.xlabel("Center orientation (deg)")
        plt.ylabel("P(Right)")
        plt.title(title_txt)
        plt.ylim(0, 1)

        if output_dir is not None:
            os.makedirs(output_dir, exist_ok=True)
            path = os.path.join(output_dir, f"psychometric_{subject}_{surr}.png")
            fig.savefig(path, bbox_inches="tight")
            plt.close(fig)
            results[surr] = path
        else:
            results[surr] = fig

    plt.show()
    return results

def plot_fixed_mocs_from_csv(
    csv_path: str,
    output_dir: Optional[str] = None,
    fit: bool = True,
    model: str = "logistic2",
):
    """Wrapper to plot fixed MOCS data from CSV file."""
    df = pd.read_csv(csv_path)
    subject = _infer_subject_from_path(csv_path)
    return plot_fixed_mocs_psychometric(df, output_dir=output_dir, fit=fit, model=model, subject=subject)

# ------------------------------
# Psychometric data & plotting from MoCS (+ logistic fits)
# ------------------------------
def mocs_psychometric_tables(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """
    Build per-surround psychometric tables (probability of 'left'/'right' vs center orientation).
    Returns dict: {'poss': df, 'negs': df, 'noss': df} for those present.
    Each df has columns: center, n, n_left, n_right, p_left, p_right
    """
    d = _clean_mocs_df(df)
    out = {}
    for s in ['poss','negs','noss']:
        g = d[d['surr_type'] == s]
        if g.empty:
            continue
        tbl = (g.groupby('center')['resp.keys']
                 .value_counts().rename('count').reset_index())
        piv = (tbl.pivot_table(index='center', columns='resp.keys',
                               values='count', fill_value=0).reset_index())
        if 'left' not in piv.columns: piv['left'] = 0
        if 'right' not in piv.columns: piv['right'] = 0
        piv = piv.rename(columns={'left':'n_left','right':'n_right'})
        piv['n'] = piv['n_left'] + piv['n_right']
        piv['p_left'] = piv['n_left'] / piv['n'].where(piv['n']>0, 1)
        piv['p_right'] = piv['n_right'] / piv['n'].where(piv['n']>0, 1)
        out[s] = piv.sort_values('center').reset_index(drop=True)
    return out

def _logistic2(x, x0, s):
    # 2-parameter logistic with lower=0, upper=1
    return 1.0 / (1.0 + np.exp(-(x - x0) / s))

def _logistic4(x, x0, s, gamma, lam):
    # 4-parameter logistic with guess (gamma) and lapse (lam)
    base = 1.0 / (1.0 + np.exp(-(x - x0) / s))
    return gamma + (1.0 - gamma - lam) * base

def _negloglik_binomial(params, x, k, n, model="logistic2"):
    # Negative log-likelihood for binomial responses
    if model == "logistic2":
        x0, s = params
        p = _logistic2(x, x0, max(s, 1e-6))
    else:
        x0, s, gamma, lam = params
        s = max(s, 1e-6)
        gamma = np.clip(gamma, 0.0, 0.2)
        lam = np.clip(lam, 0.0, 0.2)
        p = _logistic4(x, x0, s, gamma, lam)
    p = np.clip(p, 1e-6, 1-1e-6)
    return -np.sum(k * np.log(p) + (n - k) * np.log(1 - p))

def fit_psychometric_logistic(table, model="logistic2"):
    """
    Fit logistic psychometric function to an aggregated MoCS table with columns:
      center, n_left, n (prob uses p_left = n_left / n)
    model: 'logistic2' (x0, s) or 'logistic4' (x0, s, gamma, lam)
    Returns dict with 'model', 'params', 'success', and thresholds p50/p60/p70.
    """
    try:
        from scipy.optimize import minimize
    except Exception as e:
        raise RuntimeError("SciPy is required for fitting. Please install scipy.") from e

    x = table['center'].to_numpy(dtype=float)
    k = table['n_left'].to_numpy(dtype=float)
    n = table['n'].to_numpy(dtype=float)

    x0_init = np.median(x)
    s_init = max((np.max(x) - np.min(x)) / 4.0, 1e-3)

    if model == "logistic2":
        x0 = np.array([x0_init, s_init], dtype=float)
        bounds = [(-np.inf, np.inf), (1e-6, np.inf)]
    else:
        x0 = np.array([x0_init, s_init, 0.02, 0.02], dtype=float)
        bounds = [(-np.inf, np.inf), (1e-6, np.inf), (0.0, 0.2), (0.0, 0.2)]

    res = minimize(_negloglik_binomial, x0, args=(x, k, n, model), method="L-BFGS-B", bounds=bounds)
    out = {"model": model, "params": res.x.tolist(), "success": bool(res.success), "message": res.message}

    if model == "logistic2":
        x0, s = res.x
        out.update({"x0": float(x0), "s": float(s)})
        def inv_logit(p):
            p = np.clip(p, 1e-6, 1-1e-6)
            return x0 + s * np.log(p / (1 - p))
        out["threshold_p50"] = float(inv_logit(0.5))
        out["threshold_p60"] = float(inv_logit(0.6))
        out["threshold_p70"] = float(inv_logit(0.7))
    else:
        x0, s, gamma, lam = res.x
        out.update({"x0": float(x0), "s": float(s), "gamma": float(gamma), "lambda": float(lam)})
        def inv_logit4(p):
            p = np.clip(p, 1e-6, 1-1e-6)
            q = (p - gamma) / max(1e-9, (1 - gamma - lam))
            q = np.clip(q, 1e-6, 1-1e-6)
            return x0 + s * np.log(q / (1 - q))
        out["threshold_p50"] = float(inv_logit4(0.5))
        out["threshold_p60"] = float(inv_logit4(0.6))
        out["threshold_p70"] = float(inv_logit4(0.7))
    return out

def _infer_subject_from_path(csv_path: str) -> str:
    """Extract subject ID or name from filename (handles 'sub-21049999' or 'sub-jeff')."""
    base = os.path.basename(csv_path)
    # Match patterns like sub-21049999, sub-jeff, sub_21049999, etc.
    m = re.search(r"sub[-_]?([A-Za-z0-9]+)", base)
    if m:
        return m.group(1)
    # fallback: drop extension
    return os.path.splitext(base)[0]

def plot_mocs_psychometric(
    df: pd.DataFrame,
    output_dir: Optional[str] = None,
    fit: bool = True,
    model: str = "logistic2",
    subject: Optional[str] = None,
):
    """
    Plot empirical psychometric functions for poss, negs, noss.
    Adds subject info in the title and formats it cleanly.
    """
    tables = mocs_psychometric_tables(df)
    results = {}

    for surr, tab in tables.items():
        fig = plt.figure()
        x = tab["center"].to_numpy()
        y = tab["p_right"].to_numpy()
        order = np.argsort(x)
        x, y = x[order], y[order]
        plt.plot(x, y, "o-")

        # --- Build title
        subj_part = f"Subject {subject}" if subject else "Subject unknown"
        title_txt = f"{subj_part} – {surr}"

        # Add vertical line at P(50) crossing
        p50_x = _find_p50_crossing(x, y)
        if p50_x is not None:
            plt.axvline(p50_x, linestyle=":", color='gray')
            title_txt += f" (P50={p50_x:.2f})"

        if fit and len(np.unique(x)) >= 3:
            try:
                fitres = fit_psychometric_logistic(tab, model=model)
                # Compute fit curve
                xgrid = np.linspace(np.min(x), np.max(x), 200)
                if model == "logistic2":
                    yhat = _logistic2(xgrid, fitres["x0"], max(fitres["s"], 1e-6))
                else:
                    yhat = _logistic4(
                        xgrid,
                        fitres["x0"],
                        max(fitres["s"], 1e-6),
                        float(fitres.get("gamma", 0.0)),
                        float(fitres.get("lambda", 0.0)),
                    )
                plt.plot(xgrid, yhat, "-", alpha=0.7)
            except Exception as e:
                title_txt += f"\n(fit failed: {e})"

        plt.xlabel("Center orientation (deg)")
        plt.ylabel("P(Right)")
        plt.title(title_txt)
        plt.ylim(0, 1)

        if output_dir is not None:
            os.makedirs(output_dir, exist_ok=True)
            path = os.path.join(output_dir, f"psychometric_{subject}_{surr}.png")
            fig.savefig(path, bbox_inches="tight")
            plt.close(fig)
            results[surr] = path
        else:
            results[surr] = fig

    plt.show()
    return results


def plot_mocs_from_csv(
    csv_path: str,
    output_dir: Optional[str] = None,
    fit: bool = True,
    model: str = "logistic2",
):
    """Wrapper that also injects subject name into titles."""
    df = pd.read_csv(csv_path)
    subject = _infer_subject_from_path(csv_path)
    return plot_mocs_psychometric(df, output_dir=output_dir, fit=fit, model=model, subject=subject)



# ------------------------------
# Generate MOCS stimuli with fixed tilt values
# ------------------------------
def _generate_isi_values(n: int) -> list:
    """
    Generate ISI values for n trials, distributed as evenly as possible
    across 4 ISI levels: 0.5, 0.75, 1.0, 1.25.
    
    Handles cases where n doesn't divide evenly by 4 by distributing
    remainder trials across ISI levels.
    """
    isi_levels = [0.5, 0.75, 1.0, 1.25]
    base_count = n // 4
    remainder = n % 4
    
    # Distribute: first 'remainder' ISI levels get one extra trial
    isi_values = []
    for i, isi in enumerate(isi_levels):
        count = base_count + (1 if i < remainder else 0)
        isi_values.extend([isi] * count)
    
    return isi_values


def make_mocs_stimuli_fixed(
    surround_mag: float = 15.0,
    trials_per_condition: int = 36,
    poss_centers: Optional[list] = None,
    negs_centers: Optional[list] = None,
    noss_centers: Optional[list] = None,
    out_csv: Optional[str] = None
) -> pd.DataFrame:
    """
    Generate MOCS stimuli with fixed tilt values.
    
    Parameters:
    -----------
    surround_mag : float
        Magnitude of surround tilt (default 15.0)
    trials_per_condition : int
        Number of trials per center/surround combination (default 36)
        With 6 center values × 3 surround types = 18 conditions,
        36 trials each gives 648 total trials
    poss_centers : Optional[list]
        List of center angles for positive surround (default: [-2, 0, 2, 4, 6, 8])
    negs_centers : Optional[list]
        List of center angles for negative surround (default: [2, 0, -2, -4, -6, -8])
    noss_centers : Optional[list]
        List of center angles for noise surround (default: [-4, -2, -1, 1, 2, 4])
    out_csv : Optional[str]
        If provided, save the stimuli to this CSV file
    
    Returns:
    --------
    pd.DataFrame with columns: center, surround, type, surr_type, orient_opacity, noise_opacity, isi
    
    Opacity columns:
    - poss/negs: orient_opacity=100, noise_opacity=0
    - noss: orient_opacity=0, noise_opacity=100
    
    ISI values (0.5, 0.75, 1.0, 1.25) are distributed evenly across trials
    within each condition.
    """
    # Set defaults if not provided
    if poss_centers is None:
        poss_centers = [-2, 0, 2, 4, 6, 8]
    if negs_centers is None:
        negs_centers = [2, 0, -2, -4, -6, -8]
    if noss_centers is None:
        noss_centers = [-4, -2, -1, 1, 2, 4]
    
    rows = []
    
    # Positive surround
    for center in poss_centers:
        isi_values = _generate_isi_values(trials_per_condition)
        for i in range(trials_per_condition):
            rows.append({
                'center': center,
                'surround': surround_mag,
                'type': f'c{center:+d}',  # e.g., 'c-2', 'c+0', 'c+2'
                'surr_type': 'poss',
                'orient_opacity': 100,
                'noise_opacity': 0,
                'isi': isi_values[i]
            })
    
    # Negative surround
    for center in negs_centers:
        isi_values = _generate_isi_values(trials_per_condition)
        for i in range(trials_per_condition):
            rows.append({
                'center': center,
                'surround': -surround_mag,
                'type': f'c{center:+d}',
                'surr_type': 'negs',
                'orient_opacity': 100,
                'noise_opacity': 0,
                'isi': isi_values[i]
            })
    
    # Noise surround
    for center in noss_centers:
        isi_values = _generate_isi_values(trials_per_condition)
        for i in range(trials_per_condition):
            rows.append({
                'center': center,
                'surround': 0,
                'type': f'c{center:+d}',
                'surr_type': 'noss',
                'orient_opacity': 0,
                'noise_opacity': 100,
                'isi': isi_values[i]
            })
    
    df = pd.DataFrame(rows)
    
    # Sort by surround type, then center value
    surr_order = {'poss': 0, 'negs': 1, 'noss': 2}
    df['__so'] = df['surr_type'].map(surr_order)
    df = df.sort_values(['__so', 'center']).drop(columns=['__so']).reset_index(drop=True)
    
    if out_csv:
        os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
        df.to_csv(out_csv, index=False)
        print(f"Saved {len(df)} trials to {out_csv}")
    
    return df

