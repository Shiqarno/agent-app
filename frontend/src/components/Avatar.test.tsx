import '@testing-library/jest-dom'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import Avatar, { AVATAR_IDS } from './Avatar'

describe('Avatar', () => {
  it.each(AVATAR_IDS)('resolves %s to a distinct image', (avatarId) => {
    render(<Avatar avatar_id={avatarId} alt={avatarId} />)

    const img = screen.getByAltText(avatarId) as HTMLImageElement
    expect(img.tagName).toBe('IMG')
    expect(img.src).toBeTruthy()
  })

  it('every known avatar id resolves to a different image', () => {
    const sources = AVATAR_IDS.map((avatarId) => {
      const { unmount, container } = render(<Avatar avatar_id={avatarId} />)
      const src = (container.querySelector('img') as HTMLImageElement).src
      unmount()
      return src
    })

    expect(new Set(sources).size).toBe(AVATAR_IDS.length)
  })

  it('falls back without throwing for an unrecognized avatar id', () => {
    expect(() => render(<Avatar avatar_id="not_a_real_avatar" alt="fallback" />)).not.toThrow()
    const img = screen.getByAltText('fallback') as HTMLImageElement
    expect(img.src).toBeTruthy()
  })

  it('the fallback image differs from every known avatar image', () => {
    const { container: fallbackContainer } = render(<Avatar avatar_id="does_not_exist" />)
    const fallbackSrc = (fallbackContainer.querySelector('img') as HTMLImageElement).src

    for (const avatarId of AVATAR_IDS) {
      const { unmount, container } = render(<Avatar avatar_id={avatarId} />)
      const src = (container.querySelector('img') as HTMLImageElement).src
      unmount()
      expect(src).not.toBe(fallbackSrc)
    }
  })
})
