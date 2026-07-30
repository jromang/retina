// Console history navigation, filtered by prefix.
//
// The IPython convention (and that of most shells): what is already typed narrows the search.
// Typing `app.` then Up only offers lines starting with `app.`, instead of scrolling through
// two hundred unrelated entries.
//
// A pure function, tested on its own: the delicate part is not the rendering but the edges —
// what to do at the end of the list, and how to come back to the buffer being typed.

/** Direction of travel: toward the past (Up) or toward the present (Down). */
export type Direction = 'older' | 'newer';

/**
 * Next entry matching the prefix, or `null` when there are no more in that direction.
 *
 * `from` is the current index, or `null` when navigation starts — in which case we begin at the
 * end (the most recent entry). A `null` returned toward the past means "keep what you are
 * displaying"; toward the present, "come back to the buffer the user was writing". The two
 * cases are told apart by the caller, not here.
 *
 * An empty prefix turns the function into a plain traversal — the behavior before the filter.
 */
export function nextMatch(
  entries: readonly string[],
  from: number | null,
  prefix: string,
  direction: Direction,
): number | null {
  const step = direction === 'older' ? -1 : 1;
  // From the edge: the first Up must be able to reach the last entry.
  let index = from === null ? (direction === 'older' ? entries.length - 1 : entries.length) : from + step;

  while (index >= 0 && index < entries.length) {
    if ((entries[index] ?? '').startsWith(prefix)) return index;
    index += step;
  }
  return null;
}
