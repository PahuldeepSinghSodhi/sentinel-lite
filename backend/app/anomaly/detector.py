import pandas as pd
import numpy as np
from scipy import stats

def detect_anomalies(df: pd.DataFrame, reference_df: pd.DataFrame | None = None) -> list[dict]:
    """
    Detect anomalies in structured data using rule-based and statistical checks.
    
    Args:
        df: The dataframe to analyze.
        reference_df: Optional reference dataframe (e.g., rate card) for compliance checks.
    
    Returns:
        List of detected anomalies, where each anomaly is a dictionary with type,
        severity, description, details, and row_indices.
    """
    anomalies = []
    
    # 1. Duplicate Detection
    # Exclude ID and date columns -- we want to find rows with identical
    # *content* even if they have different IDs/dates (a common invoicing error)
    id_columns = {"transaction_id", "date", "invoice_ref"}
    content_columns = [c for c in df.columns if c not in id_columns]
    
    duplicates = df[df.duplicated(subset=content_columns, keep=False)]
    if not duplicates.empty:
        # Group by content columns to find sets of duplicates
        grouped = duplicates.groupby(content_columns)
        for _, group in grouped:
            if len(group) > 1:
                indices = group.index.tolist()
                anomalies.append({
                    "type": "duplicate",
                    "severity": "high",
                    "description": f"Found {len(indices)} rows with identical content (possible duplicate billing).",
                    "details": {
                        "duplicate_count": len(indices),
                        "sample_row": group.iloc[0].to_dict(),
                    },
                    "row_indices": [int(i) for i in indices]
                })
    
    # Identify numeric columns for statistical checks
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    
    # 2. Outlier Detection (Z-Score)
    for col in numeric_cols:
        col_data = df[col].dropna()
        if len(col_data) > 1:
            # scipy.stats.zscore returns a numpy array, so wrap it in a
            # Series with the same index as col_data for alignment
            z_scores = pd.Series(stats.zscore(col_data), index=col_data.index)
            outlier_mask = np.abs(z_scores) > 2
            outliers = col_data[outlier_mask]
            
            for idx, val in outliers.items():
                anomalies.append({
                    "type": "outlier_zscore",
                    "severity": "medium",
                    "description": f"Value {val} in column '{col}' is a statistical outlier (Z-score > 2).",
                    "details": {"column": col, "value": float(val), "z_score": float(z_scores[idx])},
                    "row_indices": [int(idx)]
                })
    
    # 3. Outlier Detection (IQR)
    for col in numeric_cols:
        col_data = df[col].dropna()
        if len(col_data) > 1:
            q1 = col_data.quantile(0.25)
            q3 = col_data.quantile(0.75)
            iqr = q3 - q1
            lower_bound = q1 - 1.5 * iqr
            upper_bound = q3 + 1.5 * iqr
            
            outliers = col_data[(col_data < lower_bound) | (col_data > upper_bound)]
            
            for idx, val in outliers.items():
                anomalies.append({
                    "type": "outlier_iqr",
                    "severity": "medium",
                    "description": f"Value {val} in column '{col}' falls outside expected IQR range.",
                    "details": {
                        "column": col, 
                        "value": float(val), 
                        "lower_bound": float(lower_bound), 
                        "upper_bound": float(upper_bound)
                    },
                    "row_indices": [int(idx)]
                })
                
    # 4. Rate Compliance Check
    if reference_df is not None and not reference_df.empty:
        # Expected columns for this check
        if all(c in df.columns for c in ["vendor_name", "role_level", "hourly_rate"]) and \
           all(c in reference_df.columns for c in ["vendor_name", "role_level", "approved_rate"]):
            
            # Merge to compare
            merged = df.merge(reference_df, on=["vendor_name", "role_level"], how="left")
            
            # Find where billed rate exceeds approved rate by > 5%
            # Check for NaN as well
            mask = (merged["hourly_rate"] > merged["approved_rate"] * 1.05) & (merged["approved_rate"].notna())
            violations = merged[mask]
            
            for idx, row in violations.iterrows():
                billed_rate = row["hourly_rate"]
                approved_rate = row["approved_rate"]
                diff_percent = ((billed_rate - approved_rate) / approved_rate) * 100
                
                # Severe if > 20%
                severity = "high" if diff_percent > 20 else "medium"
                
                anomalies.append({
                    "type": "rate_violation",
                    "severity": severity,
                    "description": f"Billed rate ({billed_rate}) exceeds approved rate ({approved_rate}) by {diff_percent:.1f}% for {row['vendor_name']} / {row['role_level']}.",
                    "details": {
                        "vendor_name": row["vendor_name"],
                        "role_level": row["role_level"],
                        "billed_rate": float(billed_rate),
                        "approved_rate": float(approved_rate),
                        "difference_percentage": float(diff_percent)
                    },
                    "row_indices": [int(idx)]
                })

    return anomalies
