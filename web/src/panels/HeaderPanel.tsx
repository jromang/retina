// "FITS header" panel — reading the active image's keywords.
//
// The snapshot already announced `keyword_count` and `has_wcs`: one knew there were thirty
// keywords, without being able to read a single one. The data had always existed on the
// domain side (`ImageWindow.keywords`, filled at open time); only `app.keywords` was missing,
// added along with this panel — the API first, the interface second.
//
// This is what one opens to check an exposure, a filter or a gain when a preprocessing group
// looks badly formed: the answer is always in the header.

import { useEffect, useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import { client } from '../api/client';
import { activeWindow } from '../state/store';

/** The keywords looked up first — hoisted to the top rather than buried in FITS order. */
const IMPORTANTS = [
  'OBJECT',
  'IMAGETYP',
  'FILTER',
  'EXPTIME',
  'GAIN',
  'XBINNING',
  'YBINNING',
  'SET-TEMP',
  'CCD-TEMP',
  'INSTRUME',
  'TELESCOP',
  'DATE-OBS',
];

const MUTED = 'var(--vscode-descriptionForeground)';

export function HeaderPanel() {
  const win = activeWindow.value;
  const [keywords, setKeywords] = useState<Record<string, unknown> | null>(null);
  const [filtre, setFiltre] = useState('');
  const [error, setError] = useState('');

  // Reloaded when the window changes. The keywords do not move when the pixels change: a
  // process transforms the image, not its observational identity.
  useEffect(() => {
    if (!win) {
      setKeywords(null);
      return;
    }
    let annule = false;
    void client
      .call<Record<string, unknown>>('app.keywords', { window: win.id })
      .then((mots) => {
        if (!annule) {
          setKeywords(mots);
          setError('');
        }
      })
      .catch((e: unknown) => {
        if (!annule) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      annule = true;
    };
  }, [win?.id]);

  if (!win) {
    return (
      <p style={{ color: MUTED, padding: '8px 12px', fontSize: '12px' }}>
        {m.panel_header_no_image()}
      </p>
    );
  }
  if (error) {
    return (
      <p style={{ color: 'var(--vscode-errorForeground)', padding: '8px 12px', fontSize: '12px' }}>
        {error}
      </p>
    );
  }

  const entrees = Object.entries(keywords ?? {});
  if (!entrees.length) {
    return (
      <p style={{ color: MUTED, padding: '8px 12px', fontSize: '12px' }}>
        {m.panel_header_no_keywords()}
      </p>
    );
  }

  const rang = (cle: string) => {
    const index = IMPORTANTS.indexOf(cle.toUpperCase());
    return index === -1 ? IMPORTANTS.length : index;
  };
  const requete = filtre.trim().toLowerCase();
  const lignes = entrees
    .filter(
      ([cle, valeur]) =>
        !requete
        || cle.toLowerCase().includes(requete)
        || String(valeur).toLowerCase().includes(requete),
    )
    .sort(([a], [b]) => rang(a) - rang(b) || a.localeCompare(b));

  return (
    <div style={{ display: 'grid', gap: '6px', padding: '6px 8px', minHeight: 0 }}>
      <input
        type="search"
        value={filtre}
        placeholder={m.panel_header_filter({ count: entrees.length })}
        aria-label={m.panel_header_filter_label()}
        onInput={(e) => setFiltre((e.target as HTMLInputElement).value)}
      />
      <div style={{ overflow: 'auto' }}>
        <table
          style={{
            borderCollapse: 'collapse',
            width: '100%',
            font: '11px var(--retina-font-mono)',
          }}
        >
          <tbody>
            {lignes.map(([cle, valeur]) => (
              <tr key={cle} style={{ borderTop: '1px solid var(--vscode-panel-border)' }}>
                <td style={{ padding: '2px 6px 2px 0', color: MUTED, whiteSpace: 'nowrap' }}>
                  {cle}
                </td>
                <td style={{ padding: '2px 0', wordBreak: 'break-word' }}>{String(valeur)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!lignes.length && (
          <p style={{ color: MUTED, fontSize: '12px' }}>{m.panel_header_no_match()}</p>
        )}
      </div>
      {win.has_wcs && (
        <p style={{ margin: 0, fontSize: '11px', color: MUTED }}>
          {m.panel_header_wcs()}
        </p>
      )}
    </div>
  );
}
