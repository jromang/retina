// File formats — served by the server, not listed here.
//
// The domain has a single dispatch point for extensions (`retina.io`), and it publishes it in
// the `hello` handshake. The interface builds its dialog filters and its "this format
// quantizes" warning from that, so adding a format stays a one-line change in Python. The
// grouping into named filters is presentation, and stays here; membership does not.
//
// Before the handshake — and in a test that mounts a component on its own — the signal holds a
// conservative fallback: the astro containers, which are the only formats the application has
// always read and written.

import { signal } from '@preact/signals';

import { m } from '../paraglide/messages';
import type { ImageFormats } from './types';

const FALLBACK: ImageFormats = {
  astro: ['fits', 'fit', 'fts', 'xisf'],
  float_raster: [],
  byte_raster: [],
  raw: [],
};

export const imageFormats = signal<ImageFormats>(FALLBACK);

export interface FileFilter {
  name: string;
  extensions: string[];
}

/** Filters for what the domain can **read** — astro containers, rasters and camera RAW. */
export function readFilters(): FileFilter[] {
  const f = imageFormats.value;
  const every = [...f.astro, ...f.float_raster, ...f.byte_raster, ...f.raw];
  const filters: FileFilter[] = [{ name: m.filter_astro_images(), extensions: every }];
  if (f.astro.length) filters.push({ name: m.filter_fits_xisf(), extensions: f.astro });
  const rasters = [...f.float_raster, ...f.byte_raster];
  if (rasters.length) filters.push({ name: m.filter_raster(), extensions: rasters });
  if (f.raw.length) filters.push({ name: m.filter_raw(), extensions: f.raw });
  return filters;
}

/**
 * Filters for what the domain can **write**. Camera RAW is absent, and that is not an
 * oversight: rawpy demosaics a sensor file, it does not write one back.
 */
export function writeFilters(): FileFilter[] {
  const f = imageFormats.value;
  const filters: FileFilter[] = [];
  if (f.astro.length) filters.push({ name: m.filter_fits_xisf(), extensions: f.astro });
  if (f.float_raster.length)
    filters.push({ name: m.filter_raster_float(), extensions: f.float_raster });
  if (f.byte_raster.length)
    filters.push({ name: m.filter_raster_byte(), extensions: f.byte_raster });
  return filters;
}

/** True if writing this path quantizes to 8 or 16 bits — mirror of `retina.io.is_byte_format`. */
export function isByteFormat(path: string): boolean {
  return imageFormats.value.byte_raster.includes(extensionOf(path));
}

/** True if `app.open` would know what to do with this path. */
export function isReadableImage(path: string): boolean {
  const ext = extensionOf(path);
  const f = imageFormats.value;
  return (
    f.astro.includes(ext) ||
    f.float_raster.includes(ext) ||
    f.byte_raster.includes(ext) ||
    f.raw.includes(ext)
  );
}

function extensionOf(path: string): string {
  const dot = path.lastIndexOf('.');
  return dot < 0 ? '' : path.slice(dot + 1).toLowerCase();
}
