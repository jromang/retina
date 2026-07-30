// Introspection of the object under the cursor — the logic, separated from Monaco.
//
// These functions are pure and testable without a browser; `monaco.ts` only wires them to its
// hover and signature-help providers. The separation is not cosmetic: importing `monaco.ts` in
// a test would pull in the editor's three megabytes and its worker environment.
//
// What is queried are the **live** objects of the IPython namespace, through `console.inspect`.
// No static analyzer would say what `app.active_view` is — that is the whole point of a console
// attached to the state, and the reason there is no language server here.

import { client } from '../api/client';

export interface InspectResponse {
  found: boolean;
  text: string;
  /** Call line, `f(a, b=2)` — absent for an object that is not callable. */
  definition?: string;
  /** Same, but for a class: IPython puts the signature of its `__init__` there. */
  init_definition?: string;
  docstring?: string;
}

export async function inspectAt(code: string, cursor: number): Promise<InspectResponse | null> {
  try {
    return await client.call<InspectResponse>('console.inspect', { code, cursor_pos: cursor });
  } catch {
    // The console serializes its calls on a single thread: during a long script, inspection
    // waits, then may fail. A silent hover is better than an error.
    return null;
  }
}

/**
 * Walks back to the call surrounding the cursor.
 *
 * Returns the offset of the **callee name** — that is what must be sent to the server, whose
 * `_symbol_at` expands around the offset it receives and would find, between the parentheses,
 * only the argument being typed — and the index of the parameter being entered.
 *
 * The count ignores nested groups and string contents: in `f(g(1, 2), |)` one really is at
 * parameter 1 of `f`. Without this, the slightest comma inside an argument would shift the
 * highlight.
 */
export function callContext(
  code: string,
  cursor: number,
): { calleeEnd: number; activeParameter: number } | null {
  // `calleeEnd < 0` marks a group that is not a call (list, dict, parenthesized
  // subexpression): commas are counted there, but no help is offered.
  const stack: { calleeEnd: number; commas: number }[] = [];
  let quote: string | null = null;
  for (let i = 0; i < cursor; i++) {
    const char = code[i]!;
    if (quote) {
      if (char === quote && code[i - 1] !== '\\') quote = null;
      continue;
    }
    if (char === '"' || char === "'") quote = char;
    else if (char === '(') stack.push({ calleeEnd: i, commas: 0 });
    else if (char === '[' || char === '{') stack.push({ calleeEnd: -1, commas: 0 });
    else if (char === ')' || char === ']' || char === '}') {
      if (stack.pop() === undefined) return null; // orphan closer: we do not guess
    } else if (char === ',' && stack.length > 0) {
      stack[stack.length - 1]!.commas++;
    }
  }
  const current = stack[stack.length - 1];
  if (!current || current.calleeEnd < 0) return null;
  return { calleeEnd: current.calleeEnd, activeParameter: current.commas };
}

/**
 * Splits `f(a, b=2, *args)` into its parameters, so that Monaco underlines the right one.
 *
 * The split must ignore nested commas: a default value can be a call or a list
 * (`f(a, b=g(1, 2))`), in which case a naive `split(',')` would invent one extra parameter and
 * shift the whole highlight.
 *
 * The closing parenthesis is found by matching, not by `lastIndexOf`: IPython returns the
 * return annotation (`app.open(path: 'str') -> 'ImageWindow'`), which may itself contain
 * parentheses.
 */
export function splitParameters(definition: string): string[] {
  const open = definition.indexOf('(');
  if (open < 0) return [];
  let close = -1;
  let level = 0;
  for (let i = open; i < definition.length; i++) {
    if (definition[i] === '(') level++;
    else if (definition[i] === ')' && --level === 0) {
      close = i;
      break;
    }
  }
  if (close <= open) return [];
  const inner = definition.slice(open + 1, close);
  const parts: string[] = [];
  let depth = 0;
  let current = '';
  for (const char of inner) {
    if ('([{'.includes(char)) depth++;
    else if (')]}'.includes(char)) depth--;
    if (char === ',' && depth === 0) {
      parts.push(current.trim());
      current = '';
      continue;
    }
    current += char;
  }
  if (current.trim()) parts.push(current.trim());
  return parts.filter(Boolean);
}
