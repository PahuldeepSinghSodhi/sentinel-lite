import React, { useState } from 'react';
import { ShieldAlert, Activity, AlertTriangle, AlertCircle, Loader2, ChevronDown, ChevronUp, Sparkles } from 'lucide-react';

const AnomalyTab = () => {
  const [scanning, setScanning] = useState(false);
  const [results, setResults] = useState(null);
  const [error, setError] = useState(null);
  const [expandedCards, setExpandedCards] = useState({});
  const [explanations, setExplanations] = useState({});
  const [explaining, setExplaining] = useState({});

  const handleScan = async () => {
    setScanning(true);
    setError(null);
    setExplanations({});
    try {
      const response = await fetch('http://localhost:8000/anomalies', {
        method: 'POST',
      });
      if (!response.ok) throw new Error(`API error: ${response.status}`);
      const data = await response.json();
      setResults(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setScanning(false);
    }
  };

  const handleExplain = async (idx, anomaly) => {
    setExplaining(prev => ({ ...prev, [idx]: true }));
    try {
      const response = await fetch('http://localhost:8000/explain_anomaly', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: anomaly.type,
          severity: anomaly.severity,
          description: anomaly.description,
          details: anomaly.details || {},
          row_indices: anomaly.row_indices || [],
        }),
      });
      if (!response.ok) throw new Error(`API error: ${response.status}`);
      const data = await response.json();
      setExplanations(prev => ({ ...prev, [idx]: data }));
      // Auto-expand the card when explanation arrives
      setExpandedCards(prev => ({ ...prev, [idx]: true }));
    } catch (err) {
      setExplanations(prev => ({
        ...prev,
        [idx]: { status: 'error', explanation: `Failed to get explanation: ${err.message}` },
      }));
    } finally {
      setExplaining(prev => ({ ...prev, [idx]: false }));
    }
  };

  const toggleExpanded = (idx) => {
    setExpandedCards(prev => ({ ...prev, [idx]: !prev[idx] }));
  };

  const getSeverityIcon = (severity) => {
    switch(severity) {
      case 'high': return <AlertCircle size={20} color="var(--error-color)" />;
      case 'medium': return <AlertTriangle size={20} color="var(--warning-color)" />;
      case 'low': return <Activity size={20} color="var(--success-color)" />;
      default: return null;
    }
  };

  const getTypeBadge = (type) => {
    const labels = {
      'duplicate': 'Duplicate',
      'outlier_zscore': 'Z-Score Outlier',
      'outlier_iqr': 'IQR Outlier',
      'rate_violation': 'Rate Violation',
    };
    return labels[type] || type;
  };

  const renderExplanation = (text) => {
    // Parse the bold markdown (**text**) into React elements
    const parts = text.split(/(\*\*[^*]+\*\*)/g);
    return parts.map((part, i) => {
      if (part.startsWith('**') && part.endsWith('**')) {
        return <strong key={i} style={{ color: 'var(--accent-cyan)' }}>{part.slice(2, -2)}</strong>;
      }
      return <span key={i}>{part}</span>;
    });
  };

  return (
    <div className="glass-card">
      <div className="anomalies-header">
        <div>
          <h2 style={{ margin: '0 0 0.5rem 0', color: 'white' }}>Anomaly Scanner</h2>
          <p style={{ margin: 0, color: 'var(--text-secondary)' }}>Detect duplicates, outliers, and rate violations in transaction data.</p>
        </div>
        <button className="btn-primary" onClick={handleScan} disabled={scanning}>
          {scanning ? <Loader2 className="animate-spin" size={20} /> : <ShieldAlert size={20} />}
          {scanning ? 'Scanning...' : 'Scan for Anomalies'}
        </button>
      </div>

      {error && (
        <div style={{ padding: '1rem', background: 'rgba(239, 68, 68, 0.1)', borderRadius: '0.5rem', color: 'var(--error-color)', marginTop: '1rem' }}>
          Error: {error}. Make sure the backend is running on port 8000.
        </div>
      )}

      {results && (
        <div style={{ animation: 'slideUp 0.5s ease-out' }}>
          <div className="stats-container">
            <div className="glass-card stat-card">
              <div style={{ color: 'var(--text-secondary)' }}>Total Anomalies</div>
              <div className="stat-value">{results.total_anomalies}</div>
            </div>
            <div className="glass-card stat-card">
              <div style={{ color: 'var(--text-secondary)' }}>High Severity</div>
              <div className="stat-value high">{results.severity_summary?.high || 0}</div>
            </div>
            <div className="glass-card stat-card">
              <div style={{ color: 'var(--text-secondary)' }}>Medium Severity</div>
              <div className="stat-value medium">{results.severity_summary?.medium || 0}</div>
            </div>
            <div className="glass-card stat-card">
              <div style={{ color: 'var(--text-secondary)' }}>Transactions Analyzed</div>
              <div className="stat-value">{results.transactions_analyzed}</div>
            </div>
          </div>

          <div className="anomaly-list">
            {results.anomalies?.map((anomaly, idx) => (
              <div key={idx} className={`glass-card anomaly-item ${anomaly.severity}`}>
                <div className="anomaly-header" onClick={() => toggleExpanded(idx)} style={{ cursor: 'pointer' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    {getSeverityIcon(anomaly.severity)}
                    <span style={{ fontSize: '1.1rem', fontWeight: '600' }}>{getTypeBadge(anomaly.type)}</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span className={`badge ${anomaly.severity}`}>{anomaly.severity}</span>
                    {expandedCards[idx] ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                  </div>
                </div>
                <p style={{ margin: '0.5rem 0', color: 'var(--text-secondary)' }}>{anomaly.description}</p>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
                    <strong>Affected Rows:</strong> {anomaly.row_indices?.join(', ')}
                  </div>
                  {!explanations[idx] && (
                    <button
                      className="btn-explain"
                      onClick={(e) => { e.stopPropagation(); handleExplain(idx, anomaly); }}
                      disabled={explaining[idx]}
                    >
                      {explaining[idx] ? (
                        <><Loader2 className="animate-spin" size={14} /> Analyzing...</>
                      ) : (
                        <><Sparkles size={14} /> Ask AI to Explain</>
                      )}
                    </button>
                  )}
                </div>
                
                {expandedCards[idx] && anomaly.details && !explanations[idx] && (
                  <div style={{ marginTop: '0.75rem', padding: '0.75rem', background: 'rgba(255,255,255,0.03)', borderRadius: '0.5rem', fontSize: '0.85rem' }}>
                    <strong style={{ color: 'var(--text-secondary)' }}>Raw Details:</strong>
                    <pre style={{ margin: '0.5rem 0 0', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', fontFamily: 'monospace' }}>
                      {JSON.stringify(anomaly.details, null, 2)}
                    </pre>
                  </div>
                )}

                {explanations[idx] && (
                  <div className="explanation-card" style={{ animation: 'slideUp 0.3s ease-out' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
                      <Sparkles size={16} color="var(--accent-cyan)" />
                      <strong style={{ color: 'var(--accent-cyan)', fontSize: '0.9rem' }}>AI Explanation</strong>
                    </div>
                    {explanations[idx].status === 'error' ? (
                      <p style={{ color: 'var(--error-color)', margin: 0, fontSize: '0.875rem' }}>
                        {explanations[idx].explanation}
                      </p>
                    ) : (
                      <div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', lineHeight: '1.6', whiteSpace: 'pre-line' }}>
                        {renderExplanation(explanations[idx].explanation)}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
      
      {!results && !scanning && !error && (
        <div style={{ textAlign: 'center', padding: '4rem 0', color: 'var(--text-secondary)' }}>
          <ShieldAlert size={48} style={{ opacity: 0.2, marginBottom: '1rem' }} />
          <p>Click "Scan for Anomalies" to analyze transaction data for duplicates, outliers, and rate violations.</p>
        </div>
      )}
    </div>
  );
};

export default AnomalyTab;
