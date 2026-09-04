import { useState } from 'react'
import type { CurrentUser } from '../api/auth'
import { updateMyAvatar } from '../api/users'
import Avatar from '../components/Avatar'
import AvatarPicker from '../components/AvatarPicker'

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

// Selecting in the picker only changes local, unsaved state; nothing is
// persisted (and `currentUser`/AppShell's displayed avatar does not change)
// until Save succeeds -- the backend remains authoritative.
function ProfilePage({
  currentUser,
  onUpdated,
}: {
  currentUser: CurrentUser
  onUpdated: (user: CurrentUser) => void
}) {
  const [pendingAvatarId, setPendingAvatarId] = useState(currentUser.avatar_id)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const hasChanges = pendingAvatarId !== currentUser.avatar_id

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      const updated = await updateMyAvatar(pendingAvatarId)
      onUpdated(updated)
    } catch (err) {
      setError(errorMessage(err, 'Could not update your avatar.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <h1>Profile</h1>
      <p>Signed in as {currentUser.name}</p>

      <section aria-labelledby="current-avatar-heading">
        <h2 id="current-avatar-heading">Current avatar</h2>
        <Avatar avatar_id={currentUser.avatar_id} size="lg" alt="Your current avatar" />
      </section>

      <section aria-labelledby="choose-avatar-heading">
        <h2 id="choose-avatar-heading">Choose an avatar</h2>
        <AvatarPicker value={pendingAvatarId} onChange={setPendingAvatarId} />
        {error && <p role="alert">{error}</p>}
        <button onClick={handleSave} disabled={saving || !hasChanges}>
          {saving ? 'Saving...' : 'Save'}
        </button>
      </section>
    </div>
  )
}

export default ProfilePage
