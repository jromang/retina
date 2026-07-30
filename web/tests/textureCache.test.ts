// The global texture cache: byte budget, pinning, LRU eviction.
//
// This is the piece that replaces "three textures per panel" with "a shared budget + whatever
// the screen shows cannot be evicted". The cases that carry the file: a pinned entry never
// leaves however far over budget we are, and a set that is entirely pinned beyond the budget
// evicts NOTHING — thirty visible windows must all stay displayable, that is the "no limit"
// requirement.

import { describe, expect, it } from 'vitest';

import { TextureCache, planEviction, type TextureEntry } from '../src/viewport/textureCache';

/** The tests have no GPU: any old object stands in for a WebGLTexture. */
function entry(bytes: number): TextureEntry {
  return {
    texture: { bytes } as unknown as WebGLTexture,
    quad: [1, 1],
    mono: true,
    hasAlpha: false,
    bytes,
  };
}

describe('planEviction (pure policy)', () => {
  const MB = 1e6;

  it('evicts nothing under budget', () => {
    expect(
      planEviction([{ key: 'a', bytes: 10 * MB }, { key: 'b', bytes: 20 * MB }], new Set(), 100 * MB),
    ).toEqual([]);
  });

  it('evicts oldest first, just enough to get back under budget', () => {
    const lru = [
      { key: 'old', bytes: 60 * MB },
      { key: 'mid', bytes: 60 * MB },
      { key: 'recent', bytes: 60 * MB },
    ];
    // 180 MB for a budget of 100: drop `old` (120 left) then `mid` (60 ≤ 100) — `recent`
    // survives.
    expect(planEviction(lru, new Set(), 100 * MB)).toEqual(['old', 'mid']);
  });

  it('spares the pinned ones, even the oldest', () => {
    const lru = [
      { key: 'onscreen', bytes: 90 * MB },
      { key: 'closed', bytes: 90 * MB },
    ];
    // The oldest is on screen: the most recent is the one that pays (90 MB freed > 50).
    expect(planEviction(lru, new Set(['onscreen']), 50 * MB)).toEqual(['closed']);
  });

  it('pinned entries are OUT of budget: they do not count towards the overflow', () => {
    const lru = [
      { key: 'pin1', bytes: 500 * MB },
      { key: 'free', bytes: 50 * MB },
    ];
    // 500 MB pinned + 50 free for a budget of 100: nothing to do, the 50 fit.
    expect(planEviction(lru, new Set(['pin1']), 100 * MB)).toEqual([]);
  });

  it('the spare key counts towards the budget but cannot be the victim', () => {
    // The difference with `pinned`: a freshly stored entry consumes budget (so it can force
    // older ones out) without ever being its own victim.
    const lru = [
      { key: 'old', bytes: 60 * MB },
      { key: 'fresh', bytes: 60 * MB },
    ];
    expect(planEviction(lru, new Set(), 100 * MB, 'fresh')).toEqual(['old']);
    // Even alone and over budget, the spare survives its own put.
    expect(planEviction([{ key: 'fresh', bytes: 200 * MB }], new Set(), 100 * MB, 'fresh'))
      .toEqual([]);
  });

  it('a set entirely pinned beyond the budget evicts NOTHING', () => {
    // Thirty visible windows side by side: all of them must stay displayable. The budget only
    // governs what we keep "just in case", never what the screen shows.
    const lru = Array.from({ length: 30 }, (_, i) => ({ key: `win${i}`, bytes: 100 * MB }));
    const pinned = new Set(lru.map((e) => e.key));
    expect(planEviction(lru, pinned, 100 * MB)).toEqual([]);
  });
});

describe('TextureCache', () => {
  function makeCache(budget: number) {
    const deleted: unknown[] = [];
    const cache = new TextureCache((t) => deleted.push(t), budget);
    return { cache, deleted };
  }

  it('get() touches the LRU: the key read back becomes the most recent', () => {
    const { cache } = makeCache(250);
    cache.put('a', entry(100));
    cache.put('b', entry(100));
    cache.get('a'); // a becomes recent again
    cache.put('c', entry(100)); // 300 > 250: the oldest is now b
    expect(cache.has('b')).toBe(false);
    expect(cache.has('a')).toBe(true);
    expect(cache.has('c')).toBe(true);
  });

  it('replacing a key frees the old texture', () => {
    const { cache, deleted } = makeCache(1e9);
    const first = entry(100);
    cache.put('a', first);
    cache.put('a', entry(100));
    expect(deleted).toEqual([first.texture]);
    expect(cache.totalBytes).toBe(100);
  });

  it('the entry we have just stored survives the put, even on a tight budget', () => {
    // The real flow is `put` THEN `pin`: in between, the fresh entry is protected only by the
    // grace of the put. Without it, a saturated budget would evict it before the pin and the
    // panel would display a texture that no longer exists.
    const { cache } = makeCache(50);
    cache.put('view:1', entry(100));
    expect(cache.has('view:1')).toBe(true);
  });

  it('pin(owner, keys) replaces the owner set — the stale generation becomes evictable again', () => {
    const { cache } = makeCache(50);
    cache.put('view:1', entry(100));
    cache.pin('panel', ['view:1']);
    cache.put('view:2', entry(100));
    cache.pin('panel', ['view:2']);
    expect(cache.has('view:2')).toBe(true);
    expect(cache.has('view:1')).toBe(false); // unpinned by the replacement, hence evicted
  });

  it('two owners can pin the same key; it survives as long as one remains', () => {
    // The real case: a view's viewport and its real-time preview show the same texture.
    const { cache } = makeCache(0); // zero budget: anything unpinned goes
    cache.put('view:1', entry(100));
    cache.pin('viewport', ['view:1']);
    cache.pin('rtp', ['view:1']);
    cache.unpin('viewport');
    expect(cache.has('view:1')).toBe(true);
    cache.unpin('rtp');
    expect(cache.has('view:1')).toBe(false);
  });

  it('unpin triggers eviction if the budget overflows', () => {
    const { cache, deleted } = makeCache(50);
    cache.put('big', entry(200));
    cache.pin('panel', ['big']);
    expect(cache.has('big')).toBe(true);
    cache.unpin('panel');
    expect(cache.has('big')).toBe(false);
    expect(deleted).toHaveLength(1);
  });

  it('invalidateAll forgets everything WITHOUT freeing — the handles died with the context', () => {
    const { cache, deleted } = makeCache(1e9);
    cache.put('a', entry(100));
    cache.pin('panel', ['a']);
    cache.invalidateAll();
    expect(cache.has('a')).toBe(false);
    expect(cache.totalBytes).toBe(0);
    expect(deleted).toHaveLength(0);
    // The pins survive: they state what the panels WANT to show, and the refetch after the
    // context is restored will refill those keys.
    cache.put('a', entry(100));
    cache.put('b', entry(1e9));
    expect(cache.has('a')).toBe(true);
  });
});
