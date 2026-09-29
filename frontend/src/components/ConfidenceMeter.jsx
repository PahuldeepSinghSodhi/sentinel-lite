export default function ConfidenceMeter({ score }) {
  const percentage = Math.round(
    Math.max(0, Math.min(1, Number(score) || 0)) * 100,
  );
  return (
    <div className="confidence">
      <div>
        <strong>Evidence confidence</strong>
        <span>{percentage}% · heuristic estimate</span>
      </div>
      <progress value={percentage} max="100" aria-label="Evidence confidence" />
    </div>
  );
}
