#!/usr/bin/env python3
import pandas as pd
import numpy as np
from typing import Dict, Optional

def _generate_isi_values(n: int) -> list:
    """Generate ISI values for n trials, distributed evenly across 4 ISI levels."""
    isi_levels = [0.5, 0.75, 1.0, 1.25]
    base_count = n // 4
    remainder = n % 4
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
    """Generate MOCS stimuli with fixed tilt values.
    
    Parameters:
    -----------
    poss_centers : Optional[list]
        List of center angles for positive surround (default: [-2, 0, 2, 4, 6, 8])
    negs_centers : Optional[list]
        List of center angles for negative surround (default: [2, 0, -2, -4, -6, -8])
    noss_centers : Optional[list]
        List of center angles for noise surround (default: [-4, -2, -1, 1, 2, 4])
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
                'type': f'c{center:+d}',
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
        import os
        os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
        df.to_csv(out_csv, index=False)
        print(f"Saved {len(df)} trials to {out_csv}")
    
    return df

if __name__ == '__main__':
    import os
    
    # Generate the fixed MOCS stimuli
    output_path = os.path.join('tilt_mocs', 'mocs_stims_fixed.csv')
    df = make_mocs_stimuli_fixed(out_csv=output_path)
    
    print(f"\nGenerated {len(df)} trials")
    print(f"\nFirst 10 rows:")
    print(df.head(10))
    print(f"\nLast 10 rows:")
    print(df.tail(10))
    print(f"\nColumns: {df.columns.tolist()}")
    print(f"\nDataframe shape: {df.shape}")
    
    # Verify the opacity columns
    print(f"\n--- Opacity column verification ---")
    for surr_type in ['poss', 'negs', 'noss']:
        subset = df[df['surr_type'] == surr_type]
        print(f"\n{surr_type}:")
        print(f"  orient_opacity values: {subset['orient_opacity'].unique()}")
        print(f"  noise_opacity values: {subset['noise_opacity'].unique()}")
        print(f"  Sample row: {subset.iloc[0].to_dict()}")
