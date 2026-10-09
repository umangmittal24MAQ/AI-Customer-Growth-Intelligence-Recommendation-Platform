export default function ChurnBadge({ segment }) {
  const seg = (segment || 'UNKNOWN').toUpperCase()
  const styles = {
    HIGH: 'badge badge-danger',
    MEDIUM: 'badge badge-warning',
    LOW: 'badge badge-success',
    UNKNOWN: 'badge badge-neutral',
  }
  return <span className={styles[seg] || styles.UNKNOWN}>{seg}</span>
}
