import React, { useState } from 'react';
import { Search, Loader2, Link2, FileText, Brain, Zap, ChevronDown, ChevronUp } from 'lucide-react';
import ConfidenceMeter from './ConfidenceMeter';

const QueryTab = () => {
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [deepReasoning, setDeepReasoning] = useState(false);
  const [showChain, setShowChain] = useState(false);

  const handleQuery = async (e) => {
    e.preventDefault();
    if (!question.trim()) return;

    setLoading(true);
    setError('');
    setResult(null);
    setShowChain(false);
    
    const endpoint = deepReasoning ? '/reason' : '/query';
    
    try {
      const response = await fetch(`http://localhost:8000${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, top_k: 5 })
      });
      
      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `API error: ${response.status}`);
      }
      
      const data = await response.json();
      setResult(data);
    } catch (err) {
      setError(err.message || 'An error occurred. Make sure the backend is running on port 8000.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="query-container">
      <div className="glass-card">
        <form onSubmit={handleQuery} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div className="search-box">
            <Search className="search-icon" size={24} />
            <input 
              type="text" 
              className="search-input"
              placeholder={deepReasoning 
                ? "Ask a complex question that spans multiple documents..." 
                : "Ask Sentinel any question about your documents..."}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
            />
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <button
              type="button"
              className={`btn-toggle ${deepReasoning ? 'active' : ''}`}
              onClick={() => setDeepReasoning(!deepReasoning)}
            >
              {deepReasoning ? <Brain size={16} /> : <Zap size={16} />}
              {deepReasoning ? 'Deep Reasoning (Multi-Doc)' : 'Quick Answer (Single Pass)'}
            </button>
            <button 
              type="submit" 
              className="btn-primary" 
              disabled={loading || !question.trim()}
            >
              {loading ? <Loader2 className="animate-spin" size={20} /> : <Search size={20} />}
              {loading && deepReasoning ? 'Reasoning...' : 'Ask Sentinel'}
            </button>
          </div>
        </form>
      </div>

      {error && (
        <div className="glass-card" style={{ borderColor: 'var(--error-color)' }}>
          <p style={{ color: 'var(--error-color)', margin: 0 }}>{error}</p>
        </div>
      )}

      {result && (
        <div className="glass-card answer-card" style={{ animation: 'slideUp 0.5s ease-out' }}>
          <h2 style={{ marginTop: 0, marginBottom: '1.5rem', color: 'var(--accent-cyan)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            {result.reasoning_chain ? <Brain size={22} /> : <Zap size={22} />}
            {result.reasoning_chain ? 'Multi-Doc Reasoning' : 'AI Response'}
          </h2>
          
          {/* Reasoning chain (only for multi-doc) */}
          {result.reasoning_chain && (
            <div style={{ marginBottom: '1.25rem' }}>
              <button 
                className="btn-toggle" 
                onClick={() => setShowChain(!showChain)}
                style={{ marginBottom: '0.75rem' }}
              >
                {showChain ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                {showChain ? 'Hide Reasoning Steps' : 'Show Reasoning Steps'}
                <span className="chain-badge">{result.reasoning_chain.length} steps</span>
              </button>
              
              {showChain && (
                <div className="reasoning-chain">
                  {result.reasoning_chain.map((step, i) => (
                    <div key={i} className="chain-step">
                      <div className="chain-step-header">
                        <span className="chain-step-num">{i + 1}</span>
                        <span style={{ fontWeight: 600, textTransform: 'capitalize' }}>
                          {step.step.replace(/_/g, ' ')}
                        </span>
                      </div>
                      <p style={{ margin: '0.25rem 0 0', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                        {step.description}
                      </p>
                      {step.sub_questions && (
                        <ul style={{ margin: '0.5rem 0 0', paddingLeft: '1.25rem', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                          {step.sub_questions.map((sq, j) => (
                            <li key={j}>{sq}</li>
                          ))}
                        </ul>
                      )}
                      {step.top_sources && (
                        <div style={{ marginTop: '0.35rem', fontSize: '0.8rem', color: 'var(--accent-indigo)' }}>
                          Sources: {step.top_sources.join(', ')}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="answer-content">
            {result.answer}
          </div>

          {/* Confidence meter */}
          {result.confidence && (
            <div style={{ marginTop: '1.5rem' }}>
              <ConfidenceMeter score={result.confidence.overall_confidence} />
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '0.75rem', marginTop: '0.75rem' }}>
                <div className="confidence-detail">
                  <span className="confidence-label">Retrieval</span>
                  <span className="confidence-value">{Math.round((result.confidence.retrieval_score || 0) * 100)}%</span>
                </div>
                <div className="confidence-detail">
                  <span className="confidence-label">Source Agreement</span>
                  <span className="confidence-value">{Math.round((result.confidence.source_agreement || 0) * 100)}%</span>
                </div>
                <div className="confidence-detail">
                  <span className="confidence-label">Query Coverage</span>
                  <span className="confidence-value">{Math.round((result.confidence.coverage_score || 0) * 100)}%</span>
                </div>
                <div className="confidence-detail">
                  <span className="confidence-label">Grounding</span>
                  <span className="confidence-value">{Math.round((result.confidence.answer_grounding || 0) * 100)}%</span>
                </div>
              </div>
            </div>
          )}

          {result.sources && result.sources.length > 0 && (
            <div className="sources-section">
              <h3 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '1.1rem', marginBottom: '1rem' }}>
                <Link2 size={18} /> Source Citations ({result.sources.length})
              </h3>
              
              {result.sources.map((source, i) => (
                <div key={i} className="source-card">
                  <div className="source-header">
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                      <FileText size={14} />
                      {source.source || `Document ${i+1}`}
                      {source.chunk_index !== undefined && <span style={{ opacity: 0.6 }}> (chunk {source.chunk_index})</span>}
                    </span>
                    <span>Relevance: {Math.round((source.score || 0) * 100)}%</span>
                  </div>
                  <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', margin: '0.5rem 0 0', fontStyle: 'italic', lineHeight: '1.5' }}>
                    "{source.text_preview || source.text || 'No preview available'}"
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default QueryTab;
