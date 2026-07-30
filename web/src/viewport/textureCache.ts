// Global cache of GPU textures — a single one, for all viewports.
//
// With the shared WebGL2 context (see sharedGL.ts), the textures of every window
// live in the same memory: the cache must therefore reason in **bytes**, not in a number
// of entries — the three entries of the former per-panel cache would be laughable for
// thirty windows, and an entry count says nothing about the real weight (an RTP thumbnail and a
// 61 Mpx frame do not compare).
//
// # Pinning: visible ones only
//
// Every **visible** panel pins what it is currently showing (current texture,
// curtain, mask): those entries cannot be evicted and are outside the budget. Hidden panels
// unpin themselves: measured, thirty pinned 61 Mpx color images would be 11 GB of VRAM.
// Their textures stay in the LRU — switching tabs therefore stays instantaneous in the common
// case — and under memory pressure they are evicted then re-fetched on reactivation.
// During that re-fetch, the panel's 2D canvas keeps its last blit: the old image,
// correct, stays displayed. No black, no flicker.
//
// It is this mechanism that replaces both the per-instance LRU (`MAX_TEXTURES = 3`) and the
// single mask slot of the old renderer: a mask is an ordinary entry
// (`mask:{window}:{gen}`), pinned as long as its window is visible — the objection "the LRU
// would force eviction to spare it" falls away since pinning exists for everyone.

export interface TextureEntry {
  texture: WebGLTexture;
  /** Area covered in **image** coordinates (≠ texture size for a decimated preview). */
  quad: [number, number];
  mono: boolean;
  /** The texture carries an alpha (C = 2 or 4) — see `hasAlphaChannels`. */
  hasAlpha: boolean;
  bytes: number;
}

/**
 * Budget of the NON-pinned textures. The spirit of the former `MAX_TEXTURES = 3`, but shared:
 * enough to keep several "views we have just left" (A/B toggle, recent tabs) without
 * putting the tab at risk. Pinned ones are outside the budget: what the screen shows is never
 * traded against what it might show again.
 */
export const TEXTURE_BUDGET_BYTES = 512e6;

/**
 * Eviction policy, pure so that it is testable without a GPU.
 *
 * Two protections, with different semantics: the `pinned` keys (what visible panels
 * are showing) cannot be evicted **and are outside the budget** — the screen is not traded
 * against the cache; the `spare` key (the entry a `put` has just laid down) cannot be evicted
 * but **counts towards the budget** — it consumes from it like any other, it merely has
 * the grace of this one gesture, the time for the caller to pin it.
 *
 * @param entries LRU order, oldest first — the insertion order of a `Map`
 * @returns the keys to evict, from oldest to most recent, until back under the budget
 */
export function planEviction(
  entries: ReadonlyArray<{ key: string; bytes: number }>,
  pinned: ReadonlySet<string>,
  budgetBytes: number,
  spare?: string,
): string[] {
  let unpinnedBytes = 0;
  for (const entry of entries) {
    if (!pinned.has(entry.key)) unpinnedBytes += entry.bytes;
  }
  const victims: string[] = [];
  for (const entry of entries) {
    if (unpinnedBytes <= budgetBytes) break;
    if (pinned.has(entry.key) || entry.key === spare) continue;
    victims.push(entry.key);
    unpinnedBytes -= entry.bytes;
  }
  return victims;
}

export class TextureCache {
  /** `Map` preserves insertion order: reinserting = moving to the end = most recent. */
  private readonly entries = new Map<string, TextureEntry>();
  /** Keys pinned per owner (a visible panel). A key can have N owners
   *  — the viewport and the RTP preview of the same view pin the same texture. */
  private readonly pins = new Map<string, ReadonlySet<string>>();

  constructor(
    private readonly deleteTexture: (texture: WebGLTexture) => void,
    private readonly budgetBytes = TEXTURE_BUDGET_BYTES,
  ) {}

  get(key: string): TextureEntry | undefined {
    const entry = this.entries.get(key);
    if (entry) {
      this.entries.delete(key);
      this.entries.set(key, entry); // LRU touch
    }
    return entry;
  }

  has(key: string): boolean {
    return this.entries.has(key);
  }

  /**
   * Stores a texture under its key (replacing the homonym) then evicts if the budget overflows.
   *
   * The entry just laid down is **spared within this gesture**, pinned or not: it is
   * by definition about to be shown, and the caller only pins *after* the `put`.
   * Without that grace, a tight budget would evict it in the window between the two calls —
   * it is the counterpart of the old eviction, which spared the current texture.
   */
  put(key: string, entry: TextureEntry): void {
    const replaced = this.entries.get(key);
    if (replaced && replaced.texture !== entry.texture) this.deleteTexture(replaced.texture);
    this.entries.delete(key);
    this.entries.set(key, entry);
    this.evict(key);
  }

  /**
   * Declares what an owner is showing on screen — replaces its previous set in full.
   *
   * Replacing rather than adding: the key of a stale generation leaves the set at the very
   * moment the new one enters it, without the caller having to remember to unpin.
   */
  pin(owner: string, keys: readonly string[]): void {
    if (keys.length === 0) this.pins.delete(owner);
    else this.pins.set(owner, new Set(keys));
    this.evict();
  }

  /** On unmounting a panel, or when it becomes invisible. */
  unpin(owner: string): void {
    this.pins.delete(owner);
    this.evict();
  }

  /**
   * Context loss: forget everything **without** `deleteTexture` — the handles died with
   * the context, touching them would be a no-op at best, one more error at worst.
   */
  invalidateAll(): void {
    this.entries.clear();
    // The pins stay: they describe what the panels *want* to show, and the
    // keys will be filled again by the re-fetch after restoration.
  }

  get totalBytes(): number {
    let total = 0;
    for (const entry of this.entries.values()) total += entry.bytes;
    return total;
  }

  private pinnedKeys(): Set<string> {
    const keys = new Set<string>();
    for (const set of this.pins.values()) for (const key of set) keys.add(key);
    return keys;
  }

  private evict(spare?: string): void {
    const victims = planEviction(
      [...this.entries].map(([key, entry]) => ({ key, bytes: entry.bytes })),
      this.pinnedKeys(),
      this.budgetBytes,
      spare,
    );
    for (const key of victims) {
      const entry = this.entries.get(key);
      if (entry) this.deleteTexture(entry.texture);
      this.entries.delete(key);
    }
  }
}
