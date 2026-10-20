import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import CloudShell from './CloudShell.jsx'
import { CLOUD_MODE } from './cloud.js'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {CLOUD_MODE ? <CloudShell /> : <App />}
  </React.StrictMode>,
)
