/**
 * The lines of a configuration file an edit would change, as the server's
 * unified diff gives them: added lines green, removed red.
 *
 * EXTRACTED AT THE SECOND CALLER: the settings editor drew this, and
 * describing the ontology (DEV_UI 13.7) is the second screen that shows
 * a file's change before it is written.
 */

export default function FileDiff({ lines, label }: { lines: string[]; label: string }) {
  return (
    <pre className="config-editor__diff" aria-label={label}>
      {lines.map((line, index) => (
        <span
          key={index}
          className={
            line.startsWith('+') && !line.startsWith('+++')
              ? 'config-editor__added'
              : line.startsWith('-') && !line.startsWith('---')
                ? 'config-editor__removed'
                : undefined
          }
        >
          {line}
          {'\n'}
        </span>
      ))}
    </pre>
  )
}
