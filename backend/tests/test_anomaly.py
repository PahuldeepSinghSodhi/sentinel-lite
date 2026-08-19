import os
import sys
import pandas as pd

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.anomaly.detector import detect_anomalies
from app.anomaly.router import classify_query

def main():
    print("Running Anomaly Detection Tests...")
    
    # 1. Load data
    data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
    transactions_file = os.path.join(data_dir, 'sample_transactions.csv')
    rate_card_file = os.path.join(data_dir, 'rate_card.csv')
    
    try:
        df = pd.read_csv(transactions_file)
        reference_df = pd.read_csv(rate_card_file)
    except Exception as e:
        print(f"Error loading CSV files: {e}")
        return

    # 2. Run detect_anomalies
    anomalies = detect_anomalies(df, reference_df)
    
    # 3. Print all detected anomalies
    print(f"Found {len(anomalies)} anomalies.\n")
    for a in anomalies:
        print(f"[{a['severity'].upper()}] {a['type']}: {a['description']}")
        print(f"  Details: {a['details']}")
        print(f"  Rows Affected: {a['row_indices']}\n")
        
    # 4. Asserts
    print("Running Assertions...")
    
    types = [a['type'] for a in anomalies]
    
    # Assert duplicate TXN-001/TXN-009 found
    has_duplicate = any(a['type'] == 'duplicate' for a in anomalies)
    assert has_duplicate, "Failed to find the duplicate rows (TXN-001 and TXN-009)"
    
    # Assert at least one rate violation
    rate_violations = [a for a in anomalies if a['type'] == 'rate_violation']
    assert len(rate_violations) > 0, "Failed to find any rate violations"
    has_dataflow_overcharge = any(a['details']['vendor_name'] == 'DataFlow Inc' for a in rate_violations)
    assert has_dataflow_overcharge, "Failed to find the DataFlow Inc overcharge rate violation"
    
    # Assert outlier TXN-012 found
    has_extreme_outlier = any(
        (a['type'].startswith('outlier')) and 
        (a['details'].get('value') == 950) 
        for a in anomalies
    )
    assert has_extreme_outlier, "Failed to find the extreme outlier (TXN-012 with rate 950)"
    
    print("All anomaly detection assertions passed!\n")
    
    # 5. Tests for router
    print("Running Router Tests...")
    q1 = "Check for any anomalies in the latest invoices."
    q2 = "Tell me the policy for emergency consultations."
    q3 = "What is the expected hourly rate for an Architect?"
    q4 = "Scan the database for suspicious discrepancies."
    
    assert classify_query(q1) == "analysis", f"Failed router test for: '{q1}'"
    assert classify_query(q2) == "lookup", f"Failed router test for: '{q2}'"
    assert classify_query(q3) == "lookup", f"Failed router test for: '{q3}'"
    assert classify_query(q4) == "analysis", f"Failed router test for: '{q4}'"
    
    print("All router assertions passed!")
    print("Tests completed successfully.")

if __name__ == "__main__":
    main()
