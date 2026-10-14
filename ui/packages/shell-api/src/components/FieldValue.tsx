/**
 * FieldValue -- one field's value, or which kind of absence it is.
 *
 * DEV_UI.md 9.7's fourth state, "ours alone" (specimen E4): "'Not
 * permitted', 'restricted' and a real NULL must look like three
 * different things. A hidden field is not an empty field." Three
 * surfaces each had an answer -- a pending tag on the object page and
 * in the approvals diff, an em dash in Browse -- and Browse's was
 * wrong: a field the reader may DISCOVER and not READ arrives as null
 * (mediator.get_object keeps the key and nulls the value), so a column
 * of withheld emails read as "nobody has an email address".
 *
 * WHAT THE SERVER CAN TELL APART, and so what this renders:
 *
 *   not permitted   the schema says `readable: false` for this reader
 *   not set         a null the reader was allowed to see
 *   a value         formatted by type
 *
 * "RESTRICTED" -- a readable field withheld for ONE object -- IS NOT A
 * STATE HERE, deliberately. MAC withholds whole objects, which answer
 * as not found; a link to an object the reader may not see reads as
 * null, or drops out of a many-valued list. Marking either would say
 * "something is there that you cannot see", which is the disclosure
 * uniform denial exists to prevent. So those stay indistinguishable
 * from null, and that is the security model, not an omission.
 *
 * PLAIN WORDS, NOT A TAG. DEV_UI: "Plain words chosen over a hatched
 * chip: at 13px the hatching reads as a rendering fault." And not the
 * amber `pending` tag either: amber means waiting on someone, and a
 * permission is not going to arrive by waiting.
 *
 * THE DASH SAYS "not set" TO A SCREEN READER. A bare em dash is read
 * aloud as "em dash", or as nothing, depending on the reader.
 */

import { formatValue } from '../format'

export interface FieldValueProps {
  value: unknown
  /** From the visible schema. False only when the reader may know the
   * field exists and not what it holds; undefined means readable. */
  readable?: boolean
  decimalPlaces?: number | null
  dataType?: string | null
}

export default function FieldValue({ value, readable, decimalPlaces, dataType }: FieldValueProps) {
  // FIRST, before the null check: a withheld value IS null on the wire,
  // and testing null first is exactly the conflation this exists to end.
  if (readable === false) {
    return (
      <span
        className="field-value field-value--withheld"
        title="Your role may see that this field exists, not its value"
      >
        Not permitted
      </span>
    )
  }
  if (value === null || value === undefined) {
    return (
      <span className="field-value field-value--null">
        <span aria-hidden="true">—</span>
        <span className="visually-hidden">not set</span>
      </span>
    )
  }
  return <>{formatValue(value, decimalPlaces, dataType)}</>
}
