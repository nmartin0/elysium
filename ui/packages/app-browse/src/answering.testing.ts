/**
 * A stand-in for /aggregate in a test: counts per group, answered in the
 * shape the server writes -- rows, each group named by the field it was
 * asked to group by, the count under "n" -- whichever field is asked.
 *
 * `mockImplementation(answering({ west: 3, east: 1 }))`
 */
export function answering(counts: Record<string, number>, scanTruncated = false) {
  return (_objectType: string, body: { group_by?: string }) =>
    Promise.resolve({
      rows: Object.entries(counts).map(([group, n]) => ({
        group: { [body.group_by ?? '']: group },
        metrics: { n },
      })),
      scan_truncated: scanTruncated,
    })
}
