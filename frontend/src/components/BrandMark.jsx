export default function BrandMark({ size = 36, inverse = false }) {
  return (
    <span className={`traject-mark ${inverse ? 'traject-mark-inverse' : ''}`} style={{ width: size, height: size }} aria-hidden="true">
      <svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M9 29L18.5 19.5L24 25L32 11" stroke="currentColor" strokeWidth="3.8" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M24 11H32V19" stroke="currentColor" strokeWidth="3.8" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="9" cy="29" r="3" fill="currentColor" />
      </svg>
    </span>
  )
}
