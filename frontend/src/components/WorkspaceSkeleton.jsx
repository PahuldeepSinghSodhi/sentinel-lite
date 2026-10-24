export default function WorkspaceSkeleton() {
  return <div className="workspace-skeleton" aria-label="Loading case content" aria-busy="true">
    <section className="panel skeleton-panel" aria-hidden="true">
      <span className="skeleton skeleton-kicker" /><span className="skeleton skeleton-heading" />
      <span className="skeleton skeleton-description" />
      <div className="skeleton-file-grid">{[0, 1, 2].map((slot) => <div className="skeleton-file" key={slot}>
        <span className="skeleton skeleton-icon" /><span className="skeleton skeleton-heading" />
        <span className="skeleton skeleton-description" /><span className="skeleton skeleton-description" />
      </div>)}</div>
    </section>
    <aside className="panel skeleton-panel skeleton-context" aria-hidden="true">
      <span className="skeleton skeleton-icon" /><span className="skeleton skeleton-heading" />
      <span className="skeleton skeleton-description" /><span className="skeleton skeleton-description" />
    </aside>
  </div>;
}
