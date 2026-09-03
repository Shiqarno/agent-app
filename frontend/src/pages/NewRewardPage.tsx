import { type FormEvent, useState } from 'react'
import { createReward } from '../api/rewards'
import { useRouter } from '../router'

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function NewRewardPage() {
  const { navigate } = useRouter()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [costPoints, setCostPoints] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)

    if (!name.trim()) {
      setError('Name is required.')
      return
    }
    const points = Number(costPoints)
    if (!Number.isInteger(points) || points <= 0) {
      setError('Cost must be a positive whole number.')
      return
    }

    setSubmitting(true)
    try {
      // The reward catalog is global and ownership-free; created_by remains
      // provenance only (existing business rule, unchanged by Issue #11).
      await createReward({
        name: name.trim(),
        description: description.trim() === '' ? null : description,
        cost_points: points,
      })
      navigate('/dashboard')
    } catch (err) {
      setError(errorMessage(err, 'Failed to create reward.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      <h1>Create reward</h1>
      <form onSubmit={handleSubmit}>
        <div>
          <label htmlFor="reward-name">Name</label>
          <input id="reward-name" value={name} onChange={(event) => setName(event.target.value)} />
        </div>
        <div>
          <label htmlFor="reward-description">Description</label>
          <input
            id="reward-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>
        <div>
          <label htmlFor="reward-cost">Cost (points)</label>
          <input
            id="reward-cost"
            type="number"
            value={costPoints}
            onChange={(event) => setCostPoints(event.target.value)}
          />
        </div>
        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={submitting}>
          Create reward
        </button>
      </form>
    </div>
  )
}

export default NewRewardPage
