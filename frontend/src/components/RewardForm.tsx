import { type FormEvent, useState } from 'react'

export type RewardFormValues = {
  name: string
  description: string
  costPoints: string
}

export type RewardFormSubmitValues = {
  name: string
  description: string
  cost_points: number
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

// Shared by NewRewardPage and EditRewardPage. Deliberately dumb: field
// state, the same client-side validation the backend already enforces
// (non-blank name, positive integer cost), submitting state, and mutation
// error display. What "submit" means (create vs. update, and what an empty
// description should map to) is decided by the caller's `onSubmit`.
function RewardForm({
  initialValues,
  submitLabel,
  onSubmit,
}: {
  initialValues: RewardFormValues
  submitLabel: string
  onSubmit: (values: RewardFormSubmitValues) => Promise<void>
}) {
  const [name, setName] = useState(initialValues.name)
  const [description, setDescription] = useState(initialValues.description)
  const [costPoints, setCostPoints] = useState(initialValues.costPoints)
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
      await onSubmit({ name: name.trim(), description: description.trim(), cost_points: points })
    } catch (err) {
      setError(errorMessage(err, 'Something went wrong.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
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
        {submitting ? 'Saving...' : submitLabel}
      </button>
    </form>
  )
}

export default RewardForm
