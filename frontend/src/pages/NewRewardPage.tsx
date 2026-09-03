import { createReward, type RewardInput } from '../api/rewards'
import RewardForm, { type RewardFormSubmitValues } from '../components/RewardForm'
import { useRouter } from '../router'

function NewRewardPage() {
  const { navigate } = useRouter()

  async function handleSubmit(values: RewardFormSubmitValues) {
    // The reward catalog is global and ownership-free; created_by remains
    // provenance only (existing business rule, unchanged by this issue).
    // An empty description means "no description" at creation time.
    const input: RewardInput = {
      name: values.name,
      description: values.description === '' ? null : values.description,
      cost_points: values.cost_points,
    }
    await createReward(input)
    // Reward creation always returns to /rewards, regardless of whether
    // this flow was entered from the Rewards page or the Dashboard's
    // Quick Action -- unlike Task creation, there is no dual destination.
    navigate('/rewards')
  }

  return (
    <div>
      <h1>Create reward</h1>
      <RewardForm
        initialValues={{ name: '', description: '', costPoints: '' }}
        submitLabel="Create reward"
        onSubmit={handleSubmit}
      />
    </div>
  )
}

export default NewRewardPage
