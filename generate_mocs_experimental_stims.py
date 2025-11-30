#!/usr/bin/env python3
"""
Generate MOCS experimental stimuli with fixed tilt values.

This script creates a stimulus file with:
- Positive surround: center tilts of -2, 0, 2, 4, 6, 8 degrees
- Negative surround: center tilts of 2, 0, -2, -4, -6, -8 degrees  
- No surround: center tilts of -4, -2, -1, 1, 2, 4 degrees
- 56 trials per condition = 1008 total trials

Output format is compatible with PsychoPy experiments.
"""

import staircase_to_stimuli as ss

def main():
    # Generate MOCS experimental stimuli
    df = ss.make_mocs_stimuli(
        surround_mag=15.0,              # Surround tilt magnitude in degrees
        trials_per_condition=56,         # Number of trials per center/surround combo
        out_csv='tilt_mocs/mocs_experimental_stims.csv'
    )
    
    print(f"Generated {len(df)} total trials")
    print(f"\nBreakdown by surround type:")
    for surr_type in ['poss', 'negs', 'noss']:
        count = len(df[df['surr_type'] == surr_type])
        centers = sorted(df[df['surr_type'] == surr_type]['center'].unique())
        print(f"  {surr_type}: {count} trials across {len(centers)} center values {centers}")

if __name__ == "__main__":
    main()
