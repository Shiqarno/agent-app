import { useEffect, useState } from 'react'

type HealthResponse = {
  status: string
  database: string
}

type HealthState =
  | { phase: 'loading' }
  | { phase: 'success'; data: HealthResponse }
  | { phase: 'error' }

const API_URL = 'http://localhost:8000'

function App() {
  const [state, setState] = useState<HealthState>({ phase: 'loading' })

  useEffect(() => {
    let cancelled = false

    fetch(`${API_URL}/health`)
      .then((response) => {
        if (!response.ok) {
          throw new Error('Health check failed')
        }
        return response.json() as Promise<HealthResponse>
      })
      .then((data) => {
        if (!cancelled) {
          setState({ phase: 'success', data })
        }
      })
      .catch(() => {
        if (!cancelled) {
          setState({ phase: 'error' })
        }
      })

    return () => {
      cancelled = true
    }
  }, [])

  return (
    <>
      <h1>Agent App</h1>
      {state.phase === 'loading' && <p>Loading...</p>}
      {state.phase === 'success' && (
        <>
          <p>Application: {state.data.status === 'ok' ? 'OK' : state.data.status}</p>
          <p>Database: {state.data.database === 'ok' ? 'OK' : state.data.database}</p>
        </>
      )}
      {state.phase === 'error' && <p>Unable to reach the backend.</p>}
    </>
  )
}

export default App
