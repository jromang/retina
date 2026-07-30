// Viewport shaders — GLSL ES 3.00 port of gui/stf_visual.py::_STF_GLSL.
//
// The selection of the 12 display channels (RGB, isolated channels, luminance, CIE L*a*b*, HSV,
// HSI) is copied verbatim from the VisPy shader. Only two things change.
//
// 1. Language conventions: `texture2D()` → `texture()`, VisPy's `$uniform` → real
//    uniforms, fragment output declared explicitly.
//
// 2. **The STF is evaluated analytically**, not through a LUT. The former Qt shell went through
//    a 4096-entry table because VisPy forces the colormap hook of ImageVisual; a renderer written
//    by hand does not have that constraint. The spike measured the difference on a real GPU, with
//    a typical auto-stretch (midtones ≈ 0.0027):
//
//        4096-entry LUT .......... 11.1 LSB away from the CPU computation
//        analytic MTF ............ 0.49 LSB (8-bit quantization noise)
//
//    The MTF is nearly vertical near zero: a LUT uniform over [0,1] spends only a
//    handful of steps there for the whole sky background. The analytic path is therefore not an
//    optimization, it is a correction — the web frontend is more accurate than the former Qt
//    shell on this point.

export const VERTEX_SOURCE = `#version 300 es
precision highp float;

in vec2 a_imagePos;   // image coordinates (px), y downwards
in vec2 a_uv;
uniform mat3 u_clip;  // image → clip space (see Camera.clipMatrix)
out vec2 v_uv;

void main() {
    v_uv = a_uv;
    vec3 clip = u_clip * vec3(a_imagePos, 1.0);
    gl_Position = vec4(clip.xy, 0.0, 1.0);
}
`;

export const FRAGMENT_SOURCE = `#version 300 es
precision highp float;
precision highp sampler2D;

in vec2 v_uv;
out vec4 fragColor;

uniform sampler2D u_image;
uniform float u_stfEnabled;
uniform float u_channel;     // integer code, see CHANNEL_CODE
uniform int   u_mono;        // 1 = grayscale image (red channel replicated)
uniform vec3  u_shadows;
uniform vec3  u_midtones;
uniform vec3  u_highlights;

// --- transparency (see TRANSPARENCY_CODE) ------------------------------------------
uniform int  u_hasAlpha;          // 1 = the texture carries an alpha (C = 2 or 4)
uniform int  u_transparency;      // 0 = hidden (viewport background), 1 = checkerboard, 2 = color
uniform vec3 u_transparencyColor; // flat color of the COLOR mode
uniform vec3 u_viewportBackground;

// --- mask (see MASK_MODE_CODE) -----------------------------------------------------
uniform sampler2D u_mask;
uniform int  u_maskMode;      // 0 = none, 1 = replace, 2 = multiply, 3 = tinted overlay
uniform int  u_maskInverted;
uniform int  u_maskMono;      // 1 = 1-channel mask (R16F: g and b are 0, not the data)
uniform vec3 u_maskColor;     // tint of the overlay_* modes, see MASK_OVERLAY_COLORS
uniform vec4 u_maskUv;        // (offset.xy, scale.xy): the mask covers the whole window,
                              // the displayed texture may be only a preview of it

// --- MTF: exact port of model/stf.py::mtf, edge cases included ---------------------
float mtf(float m, float x) {
    if (m <= 0.0) return 1.0;
    if (m >= 1.0) return 0.0;
    if (m == 0.5) return x;
    float den = (2.0 * m - 1.0) * x - m;
    return den == 0.0 ? 0.0 : ((m - 1.0) * x) / den;
}

// --- ChannelSTF.apply (model/stf.py:41-46) -----------------------------------------
float applyChannel(float x, float s, float m, float h) {
    float span = h - s;
    if (span <= 0.0) span = 1e-6;
    return mtf(m, clamp((x - s) / span, 0.0, 1.0));
}

// --- selection of the displayed channel ---------------------------------------------
// Extracted into a function (the cascade used to write into fragColor then return) so that the
// mask composes AFTER the channel choice: tinting first, then showing only the green channel,
// would make a red overlay disappear — the user would think they had no mask at all.
vec3 displayColor(vec3 s) {
    int ch = int(u_channel + 0.5);
    if (ch == 0) return s;
    if (ch == 1) return vec3(s.r);
    if (ch == 2) return vec3(s.g);
    if (ch == 3) return vec3(s.b);

    float mx = max(max(s.r, s.g), s.b);
    float mn = min(min(s.r, s.g), s.b);
    if (ch == 4)  return vec3(dot(s, vec3(0.2126, 0.7152, 0.0722)));
    if (ch == 10) return vec3(mx);                          // Value (HSV)
    if (ch == 11) return vec3((s.r + s.g + s.b) / 3.0);     // Intensity
    if (ch == 9)  return vec3(mx <= 0.0 ? 0.0 : (mx - mn) / mx);
    if (ch == 8) {                                          // Hue [0,1]
        float d = mx - mn; float h = 0.0;
        if (d > 1e-6) {
            if (mx == s.r) h = mod((s.g - s.b) / d, 6.0);
            else if (mx == s.g) h = (s.b - s.r) / d + 2.0;
            else h = (s.r - s.g) / d + 4.0;
            h /= 6.0;
        }
        return vec3(h);
    }
    // CIE L*a*b* from RGB (treated as linear) → XYZ (D65) → Lab, normalized to [0,1]
    mat3 M = mat3(0.4124, 0.2126, 0.0193,
                  0.3576, 0.7152, 0.1192,
                  0.1805, 0.0722, 0.9505);
    vec3 n = (M * s) / vec3(0.95047, 1.0, 1.08883);
    vec3 f = mix(7.787 * n + 16.0 / 116.0, pow(max(n, 0.0), vec3(1.0 / 3.0)), step(0.008856, n));
    if (ch == 5) return vec3((116.0 * f.y - 16.0) / 100.0);
    if (ch == 6) return vec3(500.0 * (f.x - f.y) / 256.0 + 0.5);
    if (ch == 7) return vec3(200.0 * (f.y - f.z) / 256.0 + 0.5);
    return s;
}

// --- mask weight at the current pixel ----------------------------------------------
// Replica of model/window.py::mask_array: mean of the channels, then inversion. The
// server serves the RAW mask (neither flattened nor inverted) — inversion is a display
// toggle, doing it upstream would re-upload the texture on every click on the checkbox.
float maskWeight() {
    vec4 t = texture(u_mask, u_maskUv.xy + v_uv * u_maskUv.zw);
    float m = clamp(u_maskMono == 1 ? t.r : (t.r + t.g + t.b) / 3.0, 0.0, 1.0);
    return u_maskInverted == 1 ? 1.0 - m : m;
}

// --- backdrop of the transparent areas ----------------------------------------------
// The checkerboard is computed in **device** coordinates (gl_FragCoord) and not image ones: it
// must stay fixed on screen when panning or zooming, otherwise it reads as a texture of
// the image. That is the convention of raster editors.
vec3 backdrop() {
    if (u_transparency == 0) return u_viewportBackground;
    if (u_transparency == 2) return u_transparencyColor;
    vec2 cell = floor(gl_FragCoord.xy / 8.0);
    return mix(vec3(0.25), vec3(0.36), mod(cell.x + cell.y, 2.0));
}

void main() {
    vec4 texel = texture(u_image, v_uv);
    vec3 raw = clamp(u_mono == 1 ? vec3(texel.r) : texel.rgb, 0.0, 1.0);
    // Domain convention (Image.nominal_channels): the alpha is the channel that follows the
    // nominal channels — .g for gray+alpha (C=2), .a for an RGBA (C=4).
    float alpha = u_hasAlpha == 1
        ? clamp(u_mono == 1 ? texel.g : texel.a, 0.0, 1.0)
        : 1.0;

    vec3 s = raw;
    if (u_stfEnabled > 0.5) {
        s = vec3(
            applyChannel(raw.r, u_shadows.r, u_midtones.r, u_highlights.r),
            applyChannel(raw.g, u_shadows.g, u_midtones.g, u_highlights.g),
            applyChannel(raw.b, u_shadows.b, u_midtones.b, u_highlights.b)
        );
    }

    vec3 color = displayColor(s);

    // The mask is a weight, not an image: it is composed raw, without STF. That is what
    // makes the display predictive — the gray one sees IS the blend coefficient that
    // Process.execute_on will apply. Stretching it would give a mask that promises more than it
    // protects.
    if (u_maskMode != 0) {
        float m = maskWeight();
        if (u_maskMode == 1) color = vec3(m);                 // replace: the mask alone
        else if (u_maskMode == 2) color *= m;                 // multiply
        else color = mix(u_maskColor, color, m);              // overlay: m=0 → tinted
    }

    // Transparency composes LAST: a displayed mask must stay readable
    // on top of a transparent area, otherwise looking at one's mask on a cut-out image
    // would show nothing but the checkerboard.
    if (u_hasAlpha == 1) color = mix(backdrop(), color, alpha);

    // The output is always opaque: the canvas is created with alpha:false and compositing with
    // the backdrop has already happened above. Letting the alpha through would make the render
    // depend on the *page* background, which is not the viewport's.
    fragColor = vec4(color, 1.0);
}
`;

/**
 * Channel codes — must stay in sync with ``_CHANNEL_CODE`` (gui/stf_visual.py) and
 * ``DISPLAY_CHANNELS`` (model/viewport_state.py).
 */
export const CHANNEL_CODE: Readonly<Record<string, number>> = {
  rgb: 0,
  red: 1,
  green: 2,
  blue: 3,
  L: 4,
  cie_L: 5,
  cie_a: 6,
  cie_b: 7,
  hue: 8,
  saturation: 9,
  value: 10,
  intensity: 11,
};

/**
 * Transparency modes — mirror of ``TransparencyMode`` (model/viewport_state.py).
 */
export const TRANSPARENCY_CODE = { hide: 0, brush: 1, color: 2 } as const;

/** Translates a domain `TransparencyMode` into a shader code (default: the checkerboard). */
export function transparencyCode(mode: string): number {
  if (mode === 'hide') return TRANSPARENCY_CODE.hide;
  if (mode === 'color') return TRANSPARENCY_CODE.color;
  return TRANSPARENCY_CODE.brush;
}

/** Color of the `COLOR` mode. Constant as long as the preferences do not exist. */
export const TRANSPARENCY_COLOR = [1, 1, 1] as const;

/**
 * Domain channel conventions (``Image.nominal_channels``): C=1 gray, C=2 gray+alpha,
 * C=3 RGB, C=4 RGBA. Two predicates rather than a `channels === 1` test scattered around: a
 * gray+alpha is mono *and* transparent, and forgetting that made it display as RGB.
 */
export const isMonoChannels = (channels: number): boolean => channels <= 2;
export const hasAlphaChannels = (channels: number): boolean => channels === 2 || channels === 4;

/**
 * Tints of the overlay modes — hand-written mirror of ``OVERLAY_COLORS``
 * (python/retina/model/viewport_state.py). The shader knows only three branches; it is
 * here that the eight colored modes reduce to one color.
 */
export const MASK_OVERLAY_COLORS: Readonly<Record<string, readonly [number, number, number]>> = {
  overlay_red: [1, 0, 0],
  overlay_green: [0, 1, 0],
  overlay_blue: [0, 0, 1],
  overlay_yellow: [1, 1, 0],
  overlay_magenta: [1, 0, 1],
  overlay_cyan: [0, 1, 1],
  overlay_orange: [1, 0.5, 0],
  overlay_violet: [0.6, 0, 1],
};

/** Codes of `u_maskMode`: the ten `MaskDisplayMode` values render in three ways. */
export const MASK_MODE_CODE = { off: 0, replace: 1, multiply: 2, overlay: 3 } as const;

export type MaskCompositing = {
  /** Code of `u_maskMode`. */
  mode: number;
  /** Tint, relevant to the overlay mode only. */
  color: readonly [number, number, number];
};

/**
 * Translates a domain `MaskDisplayMode` into shader settings.
 *
 * An unknown mode (domain newer than the client) falls back on the red overlay, the domain's
 * default: better to show the mask in an unexpected color than to show nothing.
 */
export function maskCompositing(displayMode: string): MaskCompositing {
  if (displayMode === 'replace') return { mode: MASK_MODE_CODE.replace, color: [1, 0, 0] };
  if (displayMode === 'multiply') return { mode: MASK_MODE_CODE.multiply, color: [1, 0, 0] };
  return {
    mode: MASK_MODE_CODE.overlay,
    color: MASK_OVERLAY_COLORS[displayMode] ?? MASK_OVERLAY_COLORS['overlay_red']!,
  };
}

/**
 * Mask texture window for the displayed view — the value of `u_maskUv`.
 *
 * The mask belongs to the **window** and covers its entire image; the texture on screen
 * may be only a preview. Without this transform, the whole mask would be squeezed into the
 * preview's rectangle — visually plausible, and completely wrong.
 *
 * @param rect (x0, y0, x1, y1) of the preview in image coordinates, absent for the main view
 */
export function maskUvTransform(
  rect: readonly [number, number, number, number] | undefined,
  windowWidth: number,
  windowHeight: number,
): [number, number, number, number] {
  if (!rect || windowWidth <= 0 || windowHeight <= 0) return [0, 0, 1, 1];
  const [x0, y0, x1, y1] = rect;
  return [x0 / windowWidth, y0 / windowHeight, (x1 - x0) / windowWidth, (y1 - y0) / windowHeight];
}

/**
 * Effective mask weight at a pixel — replica of `maskWeight()` (GLSL) and of
 * `ImageWindow.mask_array` (Python). `texel` is the quadruplet returned by the texture.
 */
export function effectiveMaskValue(
  texel: readonly [number, number, number],
  mono: boolean,
  inverted: boolean,
): number {
  const raw = mono ? texel[0] : (texel[0] + texel[1] + texel[2]) / 3;
  const m = Math.min(Math.max(raw, 0), 1);
  return inverted ? 1 - m : m;
}

/**
 * Compositing of the mask onto the display color — CPU replica of the block in `main()`.
 *
 * Exists so that it can be tested without a GPU (web/tests/mask.test.ts): the reference
 * semantics are those of `Process.execute_on` (white = processed, black = protected), and this
 * is the kind of agreement one does not want to check by eye on a screen.
 */
export function composeMaskDisplay(
  color: readonly [number, number, number],
  weight: number,
  compositing: MaskCompositing,
): [number, number, number] {
  const { mode, color: tint } = compositing;
  if (mode === MASK_MODE_CODE.off) return [color[0], color[1], color[2]];
  if (mode === MASK_MODE_CODE.replace) return [weight, weight, weight];
  if (mode === MASK_MODE_CODE.multiply) {
    return [color[0] * weight, color[1] * weight, color[2] * weight];
  }
  // mix(tint, color, weight): weight=0 (protected) → pure tint, weight=1 → image untouched
  return [
    tint[0] + (color[0] - tint[0]) * weight,
    tint[1] + (color[1] - tint[1]) * weight,
    tint[2] + (color[2] - tint[2]) * weight,
  ];
}

/**
 * TypeScript reference for the MTF — the same computation as the shader, on the CPU.
 *
 * Serves two purposes: testing the port without a GPU (vitest, see web/tests/stf.test.ts), and
 * drawing the curve in the STF panel. Any divergence from the GLSL above would be a
 * bug; the two are deliberately written identically.
 */
export function mtf(m: number, x: number): number {
  if (m <= 0) return 1;
  if (m >= 1) return 0;
  if (m === 0.5) return x;
  const den = (2 * m - 1) * x - m;
  return den === 0 ? 0 : ((m - 1) * x) / den;
}

export function applyChannelStf(
  x: number,
  shadows: number,
  midtones: number,
  highlights: number,
): number {
  let span = highlights - shadows;
  if (span <= 0) span = 1e-6;
  return mtf(midtones, Math.min(Math.max((x - shadows) / span, 0), 1));
}
