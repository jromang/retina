// Process icon, served by `/api/icons/<name>.svg`.
//
// Each of the 115 processes carries a Tabler icon name, resolved on the Python side by
// `resources/icons/registry.py` (per-process override > category icon > default) and
// carried in `ProcessMeta.icon`. It is **the** source of truth for the domain iconography:
// the frontend must not build one of its own.
//
// # Why a CSS mask and not an `<img>`
//
// Tabler SVGs are paths in `currentColor`: that is what lets them follow the
// theme, gray out when an element is disabled, turn white on a selected
// row. An `<img>` would render them in their frozen color. A `mask-image` keeps the
// hue of the surrounding text, lets the browser cache the file (the server
// sends `max-age=86400`) and avoids injecting remote HTML into the DOM.

interface Props {
  /** Tabler icon name — `ProcessMeta.icon`. */
  name: string;
  /** Side in pixels. 16 by default, like the chrome's codicons. */
  size?: number;
}

export function TablerIcon({ name, size = 16 }: Props) {
  return (
    <span
      class="tabler-icon"
      aria-hidden="true"
      style={{
        '--tabler-icon': `url("/api/icons/${encodeURIComponent(name)}.svg")`,
        width: `${size}px`,
        height: `${size}px`,
      }}
    />
  );
}
