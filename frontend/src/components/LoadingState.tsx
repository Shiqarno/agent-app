function LoadingState({ label = 'Loading...' }: { label?: string }) {
  return (
    <p className="loading-state" role="status">
      <span className="loading-state-spinner" aria-hidden="true" />
      {label}
    </p>
  )
}

export default LoadingState
