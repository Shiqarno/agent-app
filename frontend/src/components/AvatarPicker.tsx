import Avatar, { AVATAR_IDS } from './Avatar'

// A controlled selection grid over the fixed 10-avatar catalog (Issue #20).
// Selecting only updates `value` via `onChange` -- it never calls an API;
// the caller (e.g. ProfilePage) owns when/whether that selection is saved.
function AvatarPicker({
  value,
  onChange,
}: {
  value: string
  onChange: (avatarId: string) => void
}) {
  return (
    <div className="avatar-picker" role="group" aria-label="Choose an avatar">
      {AVATAR_IDS.map((avatarId) => (
        <button
          key={avatarId}
          type="button"
          aria-pressed={value === avatarId}
          className={value === avatarId ? 'avatar-option avatar-option-selected' : 'avatar-option'}
          onClick={() => onChange(avatarId)}
        >
          <Avatar avatar_id={avatarId} alt={`Avatar option ${avatarId}`} />
        </button>
      ))}
    </div>
  )
}

export default AvatarPicker
