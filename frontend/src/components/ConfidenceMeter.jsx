import React from 'react';

const ConfidenceMeter = ({ score }) => {
  // score between 0 and 1
  const percentage = Math.round(score * 100);
  
  let color = 'var(--success-color)';
  let text = 'High Confidence';
  
  if (score < 0.6) {
    color = 'var(--error-color)';
    text = 'Low Confidence';
  } else if (score < 0.8) {
    color = 'var(--warning-color)';
    text = 'Medium Confidence';
  }

  return (
    <div className="meter-container">
      <div className="meter-header">
        <span>{text}</span>
        <span>{percentage}%</span>
      </div>
      <div className="meter-track">
        <div 
          className="meter-fill" 
          style={{ width: `${percentage}%`, backgroundColor: color }}
        />
      </div>
    </div>
  );
};

export default ConfidenceMeter;
