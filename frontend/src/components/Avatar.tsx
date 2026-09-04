import type { ImgHTMLAttributes } from 'react'
import avatar01 from '../assets/avatars/avatar-01.svg'
import avatar02 from '../assets/avatars/avatar-02.svg'
import avatar03 from '../assets/avatars/avatar-03.svg'
import avatar04 from '../assets/avatars/avatar-04.svg'
import avatar05 from '../assets/avatars/avatar-05.svg'
import avatar06 from '../assets/avatars/avatar-06.svg'
import avatar07 from '../assets/avatars/avatar-07.svg'
import avatar08 from '../assets/avatars/avatar-08.svg'
import avatar09 from '../assets/avatars/avatar-09.svg'
import avatar10 from '../assets/avatars/avatar-10.svg'
import avatarFallback from '../assets/avatars/avatar-fallback.svg'

// The 10-avatar catalog (Issue #20), fixed on the backend (see
// app.models.AvatarId) -- this map is the frontend's side of that contract.
export const AVATAR_IDS = [
  'avatar_01',
  'avatar_02',
  'avatar_03',
  'avatar_04',
  'avatar_05',
  'avatar_06',
  'avatar_07',
  'avatar_08',
  'avatar_09',
  'avatar_10',
] as const

const AVATAR_SOURCES: Record<string, string> = {
  avatar_01: avatar01,
  avatar_02: avatar02,
  avatar_03: avatar03,
  avatar_04: avatar04,
  avatar_05: avatar05,
  avatar_06: avatar06,
  avatar_07: avatar07,
  avatar_08: avatar08,
  avatar_09: avatar09,
  avatar_10: avatar10,
}

const AVATAR_SIZES = {
  sm: 24,
  md: 40,
  lg: 96,
} as const

type AvatarSize = keyof typeof AVATAR_SIZES

// Purely a renderer: given an avatar_id, resolve it to its bundled image.
// Carries no notion of whose avatar this is or what role they have.
function Avatar({
  avatar_id,
  size = 'md',
  alt = 'Avatar',
  ...rest
}: {
  avatar_id: string
  size?: AvatarSize
  alt?: string
} & Omit<ImgHTMLAttributes<HTMLImageElement>, 'src' | 'width' | 'height'>) {
  const src = AVATAR_SOURCES[avatar_id] ?? avatarFallback
  const pixels = AVATAR_SIZES[size]

  return <img src={src} alt={alt} width={pixels} height={pixels} {...rest} />
}

export default Avatar
