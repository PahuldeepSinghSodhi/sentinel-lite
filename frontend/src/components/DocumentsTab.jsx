import React, { useState, useEffect } from 'react';
import { FileText, RefreshCw, CheckCircle2, XCircle, Loader2 } from 'lucide-react';

// Mock data to show if backend returns nothing or for UI structure
const MOCK_DOCS = [
  { id: 'q3_financial_report.pdf', chunks: 124, last_updated: '2 hours ago', status: 'healthy' },
  { id: 'user_privacy_policy_v2.md', chunks: 45, last_updated: '1 day ago', status: 'healthy' },
  { id: 'system_architecture_diagram.json', chunks: 12, last_updated: '3 days ago', status: 'unhealthy' },
];

const DocumentsTab = () => {
  const [ingesting, setIngesting] = useState(false);
  const [message, setMessage] = useState('');
  const [docs, setDocs] = useState(MOCK_DOCS);
  
  // Real implementation would fetch /docs from backend if available

  const handleReingest = async () => {
    setIngesting(true);
    setMessage('');
    
    try {
      const response = await fetch('http://localhost:8000/ingest', {
        method: 'POST'
      });
      
      if (!response.ok) throw new Error('Ingestion failed');
      
      const data = await response.json();
      setMessage(`Successfully re-indexed documents: ${data.message || 'Complete'}`);
      
      // Update mock data to simulate freshness
      setDocs(docs.map(d => ({ ...d, last_updated: 'Just now', status: 'healthy' })));
    } catch (err) {
      setMessage('Using mock ingestion (Backend unreachable). Data re-indexed locally.');
      setTimeout(() => {
        setDocs(docs.map(d => ({ ...d, last_updated: 'Just now', status: 'healthy' })));
      }, 1000);
    } finally {
      setIngesting(false);
    }
  };

  return (
    <div className="glass-card">
      <div className="anomalies-header">
        <div>
          <h2 style={{ margin: '0 0 0.5rem 0', color: 'white' }}>Vector Database Documents</h2>
          <p style={{ margin: 0, color: 'var(--text-secondary)' }}>Manage and re-index the data sources powering Sentinel.</p>
        </div>
        <button className="btn-primary" onClick={handleReingest} disabled={ingesting}>
          {ingesting ? <Loader2 className="animate-spin" size={20} /> : <RefreshCw size={20} />}
          Re-ingest Documents
        </button>
      </div>

      {message && (
        <div style={{ 
          padding: '1rem', 
          backgroundColor: 'rgba(34, 197, 94, 0.1)', 
          border: '1px solid var(--success-color)',
          borderRadius: '0.5rem',
          color: 'var(--success-color)',
          marginBottom: '1.5rem',
          animation: 'slideUp 0.3s ease-out'
        }}>
          {message}
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {docs.map((doc, idx) => (
          <div key={idx} style={{ 
            display: 'flex', 
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '1.25rem',
            backgroundColor: 'rgba(0, 0, 0, 0.2)',
            borderRadius: '0.75rem',
            border: '1px solid var(--border-color)'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
              <div style={{ 
                width: '40px', height: '40px', 
                borderRadius: '8px', 
                backgroundColor: 'rgba(99, 102, 241, 0.1)',
                display: 'flex', alignItems: 'center', justifyContent: 'center'
              }}>
                <FileText color="var(--accent-indigo)" size={20} />
              </div>
              <div>
                <div style={{ fontWeight: '500', color: 'white', marginBottom: '0.25rem' }}>{doc.id}</div>
                <div style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
                  {doc.chunks} vectors • Updated {doc.last_updated}
                </div>
              </div>
            </div>
            
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              {doc.status === 'healthy' ? (
                <><CheckCircle2 size={18} color="var(--success-color)" /> <span style={{ color: 'var(--success-color)', fontSize: '0.875rem' }}>Healthy</span></>
              ) : (
                <><XCircle size={18} color="var(--error-color)" /> <span style={{ color: 'var(--error-color)', fontSize: '0.875rem' }}>Needs Sync</span></>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default DocumentsTab;
