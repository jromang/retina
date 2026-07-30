// Formatting of celestial coordinates for the status bar.
//
// The domain returns **degrees** (`ImageWindow.readout`); sexagesimal is a display convention,
// so it belongs to the client. A script already has `SkyCoord.to_string()` — adding a formatter
// on the Python side would only serve the shell, and the shell does not need a round trip to
// cut a number into three.

/** Splits a decimal value into (integer, minutes, seconds), carrying rounding over. */
function sexagesimal(value: number, secondsDecimals: number): [number, number, string] {
  let units = Math.floor(value);
  let minutes = Math.floor((value - units) * 60);
  let seconds = ((value - units) * 60 - minutes) * 60;
  let text = seconds.toFixed(secondsDecimals);
  // 59.996″ rounded to three decimals gives "60.00": without a carry, we would show 12h34'60″.
  if (Number.parseFloat(text) >= 60) {
    text = (0).toFixed(secondsDecimals);
    minutes += 1;
  }
  if (minutes >= 60) {
    minutes -= 60;
    units += 1;
  }
  return [units, minutes, text];
}

const pad = (value: number) => String(value).padStart(2, '0');

/**
 * Right ascension in hours-minutes-seconds.
 *
 * The angle is brought back into [0, 360) before conversion: a WCS may return a negative value,
 * or one beyond a full turn near the prime meridian, and "−1h" does not read.
 */
export function formatRa(degrees: number, secondsDecimals = 2): string {
  const wrapped = ((degrees % 360) + 360) % 360;
  const [h, m, s] = sexagesimal(wrapped / 15, secondsDecimals);
  // 24h after a rounding carry = 0h: the turn is closed.
  return `${pad(h % 24)}h${pad(m)}m${s.padStart(secondsDecimals > 0 ? 3 + secondsDecimals : 2, '0')}s`;
}

/** Declination in signed degrees-minutes-seconds. */
export function formatDec(degrees: number, secondsDecimals = 1): string {
  const sign = degrees < 0 ? '−' : '+';
  const [d, m, s] = sexagesimal(Math.abs(degrees), secondsDecimals);
  return `${sign}${pad(d)}°${pad(m)}′${s.padStart(secondsDecimals > 0 ? 3 + secondsDecimals : 2, '0')}″`;
}

/** Both, as the status bar shows them. */
export function formatCelestial(ra: number, dec: number): string {
  return `α ${formatRa(ra)}  δ ${formatDec(dec)}`;
}
