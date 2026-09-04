import { useState } from 'react'

const DIGITS = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']

function shuffle(items: string[]): string[] {
  const result = [...items]
  for (let i = result.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[result[i], result[j]] = [result[j], result[i]]
  }
  return result
}

// Shuffled once per mount, not re-shuffled internally -- the caller gets a
// fresh layout by remounting this (e.g. a `key` that changes on Back / on a
// wrong PIN / whenever a new attempt starts), which is simpler than plumbing
// an imperative reshuffle through props.
function PinPad({
  onDigit,
  disabled,
}: {
  onDigit: (digit: string) => void
  disabled?: boolean
}) {
  const [digits] = useState(() => shuffle(DIGITS))

  return (
    <div className="pin-pad" role="group" aria-label="PIN keypad">
      {digits.map((digit) => (
        <button
          key={digit}
          type="button"
          className="pin-pad-key"
          aria-label={`Digit ${digit}`}
          disabled={disabled}
          onClick={() => onDigit(digit)}
        >
          {digit}
        </button>
      ))}
    </div>
  )
}

export default PinPad
