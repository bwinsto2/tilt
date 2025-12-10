import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

import psignifit as ps
import psignifit.psigniplot as psp

# Get data from csv mocs data file and put into format for psignifit
def get_psignifit_data_from_mocs_csv(csv_path: str) -> dict:
    """Extract data from MOCS CSV file for psignifit analysis, separated by surround type.
    
    Parameters:
    -----------
    csv_path : str
        Path to the MOCS data CSV file.
    
    Returns:
    --------
    dict
        Dictionary with keys 'poss', 'negs', 'noss', each containing an nx3 numpy array:
        - Column 0: stimulus level (center angle)
        - Column 1: number of "Right" responses (period)
        - Column 2: total number of responses
    """
    # Read the CSV file
    df = pd.read_csv(csv_path)
    
    # Filter to only main trials (exclude practice and other non-trial rows)
    # Main trials have a non-null center value and a response
    df_trials = df[df['center'].notna() & df['resp.keys'].notna()].copy()
    
    # Normalize response keys: "period" or "right" -> Right (1), "z" or "left" -> Left (0)
    # But we only count "period" or "right" as Right responses
    df_trials['is_right'] = df_trials['resp.keys'].isin(['period', 'right']).astype(int)
    
    # Dictionary to store results
    result = {}
    
    # Process each surround type separately
    for surr_type in ['poss', 'negs', 'noss']:
        # Filter by surround type
        df_surr = df_trials[df_trials['surr_type'] == surr_type].copy()
        
        # Group by stimulus level (center) and count responses
        grouped = df_surr.groupby('center').agg(
            n_right=('is_right', 'sum'),
            total=('is_right', 'count')
        ).reset_index()
        
        # Sort by stimulus level for clarity
        grouped = grouped.sort_values('center').reset_index(drop=True)
        
        # Convert to nx3 numpy array
        data = grouped[['center', 'n_right', 'total']].values
        
        result[surr_type] = data
    
    return result
    
# Fit sigmoid 
def fit_psychometric_fxn(result):
    output = {}
    for surround_cond in ['poss', 'negs', 'noss']:
        data = result[surround_cond]
        fit_result = ps.psignifit(data, experiment_type = 'equal asymptote', sigmoid = 'gauss')
        output[surround_cond] = fit_result
    return output

# Plot psychometric functions. include the PSE estimate in the title of each subplot
def plot_psychometric_fxns(fit_results, sub):
    plt.figure(figsize=(12, 4))
    for i, surround_cond in enumerate(['poss', 'negs', 'noss']):
        plt.subplot(1, 3, i+1)
        fit_result = fit_results[surround_cond]
        psp.plot_psychometric_function(fit_result)
        plt.title(f'Subject {sub} Surround: {surround_cond} \nPSE: {fit_result.parameter_estimate['threshold']:.2f}')
        plt.xlabel('Center Angle')
        plt.ylabel('Proportion Right')
    plt.tight_layout()