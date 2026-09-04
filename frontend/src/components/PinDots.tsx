function PinDots({ length, total = 4 }: { length: number; total?: number }) {
  return (
    <div className="pin-dots" role="status" aria-label={`${length} of ${total} digits entered`}>
      {Array.from({ length: total }).map((_, index) => (
        <span
          key={index}
          className={index < length ? 'pin-dot pin-dot-filled' : 'pin-dot'}
          aria-hidden="true"
        />
      ))}
    </div>
  )
}

export default PinDots
