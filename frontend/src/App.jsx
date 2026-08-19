import React, { useState } from 'react';
import { Search, ShieldAlert, FileText, Database } from 'lucide-react';
import './App.css';
import QueryTab from './components/QueryTab';
import AnomalyTab from './components/AnomalyTab';
import DocumentsTab from './components/DocumentsTab';

function App() {
  const [activeTab, setActiveTab] = useState('query');

  return (
    <div className="app-container">
      <header className="header">
        <div className="logo">
          <Database size={28} color="#6366f1" />
          <span>Sentinel-Lite</span>
        </div>
        <nav className="tabs">
          <button 
            className={`tab-button ${activeTab === 'query' ? 'active' : ''}`}
            onClick={() => setActiveTab('query')}
          >
            <Search size={18} />
            Query
          </button>
          <button 
            className={`tab-button ${activeTab === 'anomaly' ? 'active' : ''}`}
            onClick={() => setActiveTab('anomaly')}
          >
            <ShieldAlert size={18} />
            Anomaly Scanner
          </button>
          <button 
            className={`tab-button ${activeTab === 'documents' ? 'active' : ''}`}
            onClick={() => setActiveTab('documents')}
          >
            <FileText size={18} />
            Documents
          </button>
        </nav>
      </header>

      <main className="main-content">
        {activeTab === 'query' && <QueryTab />}
        {activeTab === 'anomaly' && <AnomalyTab />}
        {activeTab === 'documents' && <DocumentsTab />}
      </main>
    </div>
  );
}

export default App;
