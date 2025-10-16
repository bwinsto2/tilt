
import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional

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
    n_conditions: int = 5
) -> pd.DataFrame:
    """
    Create a stimuli/conditions table that matches practice_stims.csv columns:
      ['center','surround','type','surr_type','surr_opacity']

    Choose `n_conditions`:
      - 5-condition: m2, m1, PSE, p1, p2  (offsets = ±2*step and ±1*step)
      - 7-condition: m3, m2, m1, PSE, p1, p2, p3 (offsets = ±3*step, ±2*step, ±1*step)
    Naming: m1=1*step, m2=2*step, m3=3*step (and p1/p2/p3 accordingly)
    """
    for key in ['poss','negs','noss']:
        if key not in pse_by_condition:
            raise ValueError("pse_by_condition must include 'poss', 'negs', and 'noss'.")

    if n_conditions == 5:
        offsets = [('m2', -2*step), ('m1', -1*step), ('PSE', 0.0), ('p1', +1*step), ('p2', +2*step)]
    elif n_conditions == 7:
        offsets = [('m3', -3*step), ('m2', -2*step), ('m1', -1*step), ('PSE', 0.0), ('p1', +1*step), ('p2', +2*step), ('p3', +3*step)]
    else:
        raise ValueError('n_conditions must be 5 or 7')

    rows = []

    # poss
    pse = float(pse_by_condition['poss'])
    for tname, delta in offsets:
        level = abs(pse + delta)
        for _ in range(int(reps_poss_negs)):
            rows.append({'center': +level, 'surround': +abs(surround_mag), 'type': tname, 'surr_type': 'poss', 'surr_opacity': 100})

    # negs
    pse = float(pse_by_condition['negs'])
    for tname, delta in offsets:
        level = abs(pse + delta)
        for _ in range(int(reps_poss_negs)):
            rows.append({'center': -level, 'surround': -abs(surround_mag), 'type': tname, 'surr_type': 'negs', 'surr_opacity': 100})

    # noss (single sign based on PSE_noss)
    pse = float(pse_by_condition['noss'])
    base_sign = +1.0 if pse >= 0 else -1.0
    for tname, delta in offsets:
        level = base_sign * abs(pse + delta)
        for _ in range(int(reps_noss)):
            rows.append({'center': level, 'surround': 0, 'type': tname, 'surr_type': 'noss', 'surr_opacity': 0})

    out = pd.DataFrame(rows, columns=PRACTICE_COLS)
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
# Psychometric data & plotting from MoCS (+ logistic fits)
# ------------------------------
def mocs_psychometric_tables(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """
    Build per-surround psychometric tables (probability of 'left' vs center orientation).
    Returns dict: {'poss': df, 'negs': df, 'noss': df} for those present.
    Each df has columns: center, n, n_left, p_left
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

def plot_mocs_psychometric(df: pd.DataFrame, output_dir: Optional[str] = None, fit: bool = True, model: str = "logistic2"):
    """
    Plot empirical psychometric functions for poss, negs, noss:
      - x-axis: center orientation (deg)
      - y-axis: P(Left)
    If `fit` is True, overlays a logistic curve fit (model: 'logistic2' or 'logistic4').
    If output_dir is provided, saves PNGs there and returns dict of paths;
    otherwise returns dict of matplotlib Figure objects.
    """
    tables = mocs_psychometric_tables(df)
    results = {}
    for surr, tab in tables.items():
        fig = plt.figure()
        x = tab['center'].to_numpy()
        y = tab['p_left'].to_numpy()
        order = np.argsort(x)
        x = x[order]; y = y[order]
        plt.plot(x, y, 'o-')
        title_txt = f"MoCS psychometric – {surr}"
        if fit and len(np.unique(x)) >= 3:
            try:
                fitres = fit_psychometric_logistic(tab, model=model)
                xgrid = np.linspace(np.min(x), np.max(x), 200)
                if model == "logistic2":
                    yhat = _logistic2(xgrid, fitres["x0"], max(fitres["s"], 1e-6))
                else:
                    yhat = _logistic4(xgrid, fitres["x0"], max(fitres["s"], 1e-6),
                                      float(fitres.get("gamma", 0.0)),
                                      float(fitres.get("lambda", 0.0)))
                #plt.plot(xgrid, yhat, '-')
                title_txt += "\\n" + f"P50={fitres['threshold_p50']:.3g}, P60={fitres['threshold_p60']:.3g}, P70={fitres['threshold_p70']:.3g}"
            except Exception as e:
                title_txt += f" (fit failed: {e})"
        plt.xlabel("Center orientation (deg)")
        plt.ylabel("P(Left)")
        plt.title(title_txt)
        plt.ylim(0, 1)
        plt.axhline(0.5, linestyle=':')
        if output_dir is not None:
            import os
            os.makedirs(output_dir, exist_ok=True)
            path = os.path.join(output_dir, f"psychometric_{surr}.png")
            fig.savefig(path, bbox_inches="tight")
            plt.close(fig)
            results[surr] = path
        else:
            results[surr] = fig
    plt.show()
    return results

# ------------------------------
# CSV plotting wrapper
# ------------------------------
def plot_mocs_from_csv(csv_path: str, output_dir: Optional[str] = None, fit: bool = True, model: str = "logistic2"):
    """
    Convenience wrapper: load a MoCS CSV and plot psychometric functions.
    Args:
        csv_path: path to a MoCS data CSV with columns ['type','surr_type','resp.keys','center']
        output_dir: if given, save one PNG per surround condition and return dict of paths
        fit: whether to overlay logistic fits
        model: 'logistic2' or 'logistic4'
    Returns:
        Dict[str, str|matplotlib.figure.Figure]: keys are 'poss','negs','noss' (as available)
    """
    df = pd.read_csv(csv_path)
    return plot_mocs_psychometric(df, output_dir=output_dir, fit=fit, model=model)
