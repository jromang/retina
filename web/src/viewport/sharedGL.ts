// The application's WebGL2 context — ONE only, shared by every viewport.
//
// # Why a single context
//
// The browser only keeps a handful of WebGL contexts alive (measured: 16 on
// Chromium); beyond that, it silently kills the oldest ones, and the affected viewport stays
// black. One context per panel therefore capped the application at about fifteen open
// windows — *hidden* tabs included, since dockview keeps the panels mounted. A single
// context removes the cap: it is the architecture of professional multi-viewport
// viewers (medical imaging), and the only one that allows as many viewports
// *visible side by side* as one wants.
//
// # The blit pact
//
// The canvas of this context is hidden, never inserted into the DOM. Each panel renders into it
// then copies the result to its visible canvas — a **2D** canvas — through `drawImage`. The
// context is created without `preserveDrawingBuffer` (keeping it costs on every frame): the
// buffer is only readable up to compositing, that is **within the task that drew**. Hence the
// absolute rule: draw and blit in the same synchronous call, never an `await` between the
// two. `ViewportRenderer.render()` encapsulates the sequence so that no caller can
// cut it.
//
// Side benefit of the 2D canvas: it **keeps its last blit** (a WebGL canvas is
// cleared on every frame). A reactivated tab whose texture has been evicted shows the old
// image — a correct one — during the re-fetch: no black, no flicker.
//
// # Loss and restoration
//
// A single context = a single possible loss (GPU reset, driver update). It is
// handled here and nowhere else: `webglcontextlost` invalidates the cache (the handles are
// dead), `webglcontextrestored` recompiles the plumbing and increments `glEpoch` — the signal
// the panels' loading effects depend on, which then re-fetch their pixels
// (they live on the server side, nothing is lost).

import { signal } from '@preact/signals';

import { m } from '../paraglide/messages';
import type { StfChannel } from '../api/types';
import {
  CHANNEL_CODE,
  FRAGMENT_SOURCE,
  MASK_MODE_CODE,
  TRANSPARENCY_COLOR,
  VERTEX_SOURCE,
} from './shaders';
import { TextureCache } from './textureCache';

export interface Capabilities {
  renderer: string;
  vendor: string;
  maxTextureSize: number;
  /** True if the driver can interpolate float32 textures (useless for our f16). */
  floatLinear: boolean;
}

/**
 * Epoch of the context: incremented on every restoration after a loss.
 *
 * The panels' loading effects put it in their dependencies: a bump makes them
 * re-fetch their pixels and refill the cache. That is the whole recovery protocol.
 */
export const glEpoch = signal(0);

const UNIFORMS = [
  'u_clip',
  'u_image',
  'u_stfEnabled',
  'u_channel',
  'u_mono',
  'u_shadows',
  'u_midtones',
  'u_highlights',
  'u_mask',
  'u_maskMode',
  'u_maskInverted',
  'u_maskMono',
  'u_maskColor',
  'u_maskUv',
  'u_hasAlpha',
  'u_transparency',
  'u_transparencyColor',
  'u_viewportBackground',
] as const;

type UniformName = (typeof UNIFORMS)[number];

const IDENTITY_STF: StfChannel = { shadows: 0, midtones: 0.5, highlights: 1 };
/** Viewport background — same value as the CSS token `--retina-viewport-background`. */
const CLEAR = [0.063, 0.063, 0.078] as const;

/** Everything a draw call must know — the per-panel renderer touches no gl.* at all. */
export interface QuadPass {
  texture: WebGLTexture;
  /** Area covered in image coordinates (camera) — the quad of the vertices. */
  quad: readonly [number, number];
  /** Origin of the quad in image coordinates — (0,0) except for a mosaic tile. */
  origin?: readonly [number, number];
  /** The panel's image → clip matrix (`camera.clipMatrix()`). */
  clip: Float32Array;
  mono: boolean;
  /** The texture carries an alpha channel (C = 2 or 4) to compose over the backdrop. */
  hasAlpha: boolean;
  /** Render mode of the transparent areas, see `TRANSPARENCY_CODE`. */
  transparency: number;
  stfEnabled: boolean;
  stfChannels: readonly StfChannel[];
  channel: string;
  mask: {
    texture: WebGLTexture | null;
    mono: boolean;
    mode: number;
    inverted: boolean;
    color: readonly [number, number, number];
    uv: readonly [number, number, number, number];
  };
}

/**
 * Sub-rectangle of the GL canvas to blit for a rendered region of `w`×`h`.
 *
 * The region is anchored at the **GL** origin, which is the bottom-left corner; seen from the 2D
 * side (origin at top left), it therefore occupies the BOTTOM of the canvas: `sy = glHeight − h`.
 * Getting this wrong breaks nothing noisily — one simply blits the wrong half of a larger canvas,
 * and the image looks offset or empty depending on the size. Hence the dedicated test.
 */
export function blitSourceRect(
  glHeight: number,
  w: number,
  h: number,
): { sx: number; sy: number; sw: number; sh: number } {
  return { sx: 0, sy: Math.max(0, glHeight - h), sw: w, sh: h };
}

/**
 * Next size of the hidden GL canvas: grows component by component, never shrinks.
 *
 * Reallocating the drawing buffer is the expensive operation — it is paid on the first
 * appearance of a large viewport, not on every switch. The worst case is bounded by the browser
 * window (a viewport cannot be larger), that is ~132 MB of RGBA8 at 4K DPR 2.
 */
export function nextCanvasSize(
  current: readonly [number, number],
  needed: readonly [number, number],
  max: number,
): [number, number] {
  return [
    Math.min(Math.max(current[0], needed[0], 1), max),
    Math.min(Math.max(current[1], needed[1], 1), max),
  ];
}

export class SharedGL {
  readonly canvas: HTMLCanvasElement;
  gl: WebGL2RenderingContext;
  caps: Capabilities;
  readonly cache: TextureCache;

  private program!: WebGLProgram;
  private uniforms = new Map<UniformName, WebGLUniformLocation | null>();
  private vao!: WebGLVertexArrayObject;
  private vbo!: WebGLBuffer;
  private lost = false;

  constructor() {
    this.canvas = document.createElement('canvas');
    this.canvas.width = 1;
    this.canvas.height = 1;
    const gl = this.canvas.getContext('webgl2', {
      antialias: false,
      alpha: false,
      depth: false,
      stencil: false,
      powerPreference: 'high-performance',
      preserveDrawingBuffer: false,
    });
    if (!gl) throw new Error(m.gl_unavailable());
    this.gl = gl;
    this.caps = probe(gl);
    this.cache = new TextureCache((texture) => this.gl.deleteTexture(texture));
    this.buildPipeline();

    // The loss events fire on the canvas element, whether it is attached to the DOM or not.
    this.canvas.addEventListener('webglcontextlost', (event) => {
      // Without preventDefault, the browser will NEVER offer restoration.
      event.preventDefault();
      this.lost = true;
      this.cache.invalidateAll();
    });
    this.canvas.addEventListener('webglcontextrestored', () => {
      // The context is the same JS object, but everything that lived inside it is dead:
      // probe the caps again (a reset can change GPU) and recompile the plumbing.
      this.caps = probe(this.gl);
      this.buildPipeline();
      this.lost = false;
      glEpoch.value += 1;
    });
  }

  isLost(): boolean {
    return this.lost || this.gl.isContextLost();
  }

  /** Grows the hidden canvas to cover `width`×`height` (grow-only, clamped to the caps). */
  ensureSize(width: number, height: number): void {
    const [w, h] = nextCanvasSize(
      [this.canvas.width, this.canvas.height],
      [width, height],
      this.caps.maxTextureSize,
    );
    if (w !== this.canvas.width || h !== this.canvas.height) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
  }

  /**
   * Opens a render region (0,0,w,h): viewport, scissor and backdrop.
   *
   * The scissor is not optional: `gl.clear` **ignores the viewport** but respects the
   * scissor. Without it, every panel would clear the whole shared canvas — invisible as long
   * as a single panel renders per frame, wrong from the first simultaneous resize on.
   */
  beginRegion(width: number, height: number): void {
    const gl = this.gl;
    gl.viewport(0, 0, width, height);
    gl.enable(gl.SCISSOR_TEST);
    gl.scissor(0, 0, width, height);
    gl.clearColor(CLEAR[0], CLEAR[1], CLEAR[2], 1);
    gl.clear(gl.COLOR_BUFFER_BIT);
  }

  endRegion(): void {
    this.gl.disable(this.gl.SCISSOR_TEST);
  }

  /**
   * Draws a quad with a panel's full state. `scissor` restricts the drawing (curtain,
   * magnifier) without touching the viewport — the coordinates stay those of the region.
   */
  drawQuad(pass: QuadPass, scissor?: { x: number; y: number; w: number; h: number }): void {
    const gl = this.gl;
    if (scissor) gl.scissor(scissor.x, scissor.y, scissor.w, scissor.h);

    const [ox, oy] = pass.origin ?? [0, 0];
    this.setQuad(ox, oy, pass.quad[0], pass.quad[1]);
    gl.useProgram(this.program);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, pass.texture);
    gl.uniform1i(this.uniforms.get('u_image') ?? null, 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, pass.mask.texture);
    gl.uniform1i(this.uniforms.get('u_mask') ?? null, 1);
    gl.activeTexture(gl.TEXTURE0);
    this.bindUniforms(pass);
    gl.bindVertexArray(this.vao);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    gl.bindVertexArray(null);
  }

  /** Temporary scissored viewport for the magnifier — region frame, as in `drawQuad`. */
  withViewport(
    rect: { x: number; y: number; w: number; h: number },
    draw: () => void,
  ): void {
    const gl = this.gl;
    // The scissor test must be ACTIVE for the clear to stay bounded to the magnifier's rectangle:
    // `render()` has closed its region (`endRegion` → `disable(SCISSOR_TEST)`) before the
    // magnifier is added, so without this `enable` the clear would ignore the scissor and wipe the
    // whole canvas — the backdrop would vanish, only the magnifier surviving. `endRegion`
    // disables it again.
    gl.enable(gl.SCISSOR_TEST);
    gl.viewport(rect.x, rect.y, rect.w, rect.h);
    gl.scissor(rect.x, rect.y, rect.w, rect.h);
    gl.clearColor(CLEAR[0], CLEAR[1], CLEAR[2], 1);
    gl.clear(gl.COLOR_BUFFER_BIT);
    draw();
  }

  /**
   * Creates and fills an f16 texture (H, W, C). `filter`: LINEAR for an image, NEAREST for
   * a mask (an interpolated weight would lie about what the process will apply).
   */
  createTexture(
    buffer: ArrayBuffer,
    width: number,
    height: number,
    channels: number,
    filter: 'linear' | 'nearest',
  ): WebGLTexture {
    const gl = this.gl;
    if (width > this.caps.maxTextureSize || height > this.caps.maxTextureSize) {
      throw new Error(
        m.gl_texture_too_large({ width, height, max: this.caps.maxTextureSize }),
      );
    }
    // The buffer must carry AT LEAST width×height×channels half-floats. Letting
    // `texImage2D` notice it gave a mute "GL 0x502", which was expensive to
    // diagnose: the real culprit was a stale HTTP response (cache from a previous
    // session), and nothing in the message let one guess it.
    //
    // We reproduce WebGL's rule — *too small* is an error, *larger* is legal
    // (the excess is ignored) — rather than a strict equality: a caller that uploads
    // a sub-region of a larger buffer is legitimate, and forbidding it would break
    // paths that used to work.
    const expected = width * height * channels * 2;
    if (buffer.byteLength < expected) {
      throw new Error(
        m.gl_buffer_size_mismatch({
          width, height, channels, got: buffer.byteLength, want: expected,
        }),
      );
    }
    const texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    const mode = filter === 'linear' ? gl.LINEAR : gl.NEAREST;
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, mode);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, mode);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    // One channel per component: gray+alpha (C=2) must go up as RG, not as RGBA — the
    // upload would otherwise read twice as many bytes as the buffer carries.
    const [internalFormat, format] =
      channels === 1
        ? [gl.R16F, gl.RED]
        : channels === 2
          ? [gl.RG16F, gl.RG]
          : channels === 3
            ? [gl.RGB16F, gl.RGB]
            : [gl.RGBA16F, gl.RGBA];
    gl.texImage2D(
      gl.TEXTURE_2D, 0, internalFormat, width, height, 0, format, gl.HALF_FLOAT,
      new Uint16Array(buffer),
    );
    const error = gl.getError();
    if (error !== gl.NO_ERROR) {
      gl.deleteTexture(texture);
      throw new Error(m.gl_upload_failed({ code: error.toString(16) }));
    }
    return texture;
  }

  private buildPipeline(): void {
    const gl = this.gl;
    this.program = buildProgram(gl);
    this.uniforms = new Map();
    for (const name of UNIFORMS) {
      this.uniforms.set(name, gl.getUniformLocation(this.program, name));
    }
    const { vao, vbo } = buildQuad(gl, this.program);
    this.vao = vao;
    this.vbo = vbo;
  }

  private setQuad(x0: number, y0: number, width: number, height: number): void {
    const gl = this.gl;
    // triangle strip (x0,y0) (x0+W,y0) (x0,y0+H) (x0+W,y0+H) in image coordinates, uv 0→1:
    // each tile is its own texture (CLAMP_TO_EDGE), so the UVs stay full.
    // v = iy/H without a flip: texel 0 is the first row of data, which the y-downwards image
    // convention places at the top — this is the counterpart of the VisPy camera's flip.
    const x1 = x0 + width;
    const y1 = y0 + height;
    const vertices = new Float32Array([
      x0, y0, 0, 0,
      x1, y0, 1, 0,
      x0, y1, 0, 1,
      x1, y1, 1, 1,
    ]);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo);
    gl.bufferSubData(gl.ARRAY_BUFFER, 0, vertices);
  }

  private bindUniforms(pass: QuadPass): void {
    const gl = this.gl;
    gl.uniformMatrix3fv(this.uniforms.get('u_clip') ?? null, false, pass.clip);
    gl.uniform1f(this.uniforms.get('u_stfEnabled') ?? null, pass.stfEnabled ? 1 : 0);
    gl.uniform1f(this.uniforms.get('u_channel') ?? null, CHANNEL_CODE[pass.channel] ?? 0);
    gl.uniform1i(this.uniforms.get('u_mono') ?? null, pass.mono ? 1 : 0);

    const at = (index: number): StfChannel =>
      pass.stfChannels[Math.min(index, pass.stfChannels.length - 1)] ?? IDENTITY_STF;
    gl.uniform3f(this.uniforms.get('u_shadows') ?? null, at(0).shadows, at(1).shadows, at(2).shadows);
    gl.uniform3f(
      this.uniforms.get('u_midtones') ?? null,
      at(0).midtones, at(1).midtones, at(2).midtones,
    );
    gl.uniform3f(
      this.uniforms.get('u_highlights') ?? null,
      at(0).highlights, at(1).highlights, at(2).highlights,
    );

    // Without a texture, the mode is forced to 0: the shader must never sample an
    // unbound unit, and a mask announced but not yet arrived must not blacken the image.
    const mode = pass.mask.texture === null ? MASK_MODE_CODE.off : pass.mask.mode;
    gl.uniform1i(this.uniforms.get('u_maskMode') ?? null, mode);
    gl.uniform1i(this.uniforms.get('u_maskInverted') ?? null, pass.mask.inverted ? 1 : 0);
    gl.uniform1i(this.uniforms.get('u_maskMono') ?? null, pass.mask.mono ? 1 : 0);
    gl.uniform3f(this.uniforms.get('u_maskColor') ?? null, ...pass.mask.color);
    gl.uniform4f(this.uniforms.get('u_maskUv') ?? null, ...pass.mask.uv);

    gl.uniform1i(this.uniforms.get('u_hasAlpha') ?? null, pass.hasAlpha ? 1 : 0);
    gl.uniform1i(this.uniforms.get('u_transparency') ?? null, pass.transparency);
    gl.uniform3f(this.uniforms.get('u_transparencyColor') ?? null, ...TRANSPARENCY_COLOR);
    gl.uniform3f(this.uniforms.get('u_viewportBackground') ?? null, ...CLEAR);
  }
}

let instance: SharedGL | null = null;

/** The singleton, created lazily at the first viewport. */
export function sharedGL(): SharedGL {
  if (!instance) {
    instance = new SharedGL();
    // Diagnostic hook: DevTools → __retinaGL.gl.getExtension('WEBGL_lose_context')
    // .loseContext() / .restoreContext() to exercise the recovery path by hand.
    (globalThis as Record<string, unknown>)['__retinaGL'] = instance;
  }
  return instance;
}

function probe(gl: WebGL2RenderingContext): Capabilities {
  const debug = gl.getExtension('WEBGL_debug_renderer_info');
  return {
    renderer: debug ? String(gl.getParameter(debug.UNMASKED_RENDERER_WEBGL)) : m.gl_unknown(),
    vendor: debug ? String(gl.getParameter(debug.UNMASKED_VENDOR_WEBGL)) : m.gl_unknown(),
    maxTextureSize: gl.getParameter(gl.MAX_TEXTURE_SIZE) as number,
    floatLinear: gl.getExtension('OES_texture_float_linear') !== null,
  };
}

function compile(gl: WebGL2RenderingContext, type: number, source: string): WebGLShader {
  const shader = gl.createShader(type);
  if (!shader) throw new Error(m.gl_shader_create_failed());
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    throw new Error(m.gl_shader_compile_failed({ log: String(gl.getShaderInfoLog(shader)) }));
  }
  return shader;
}

function buildProgram(gl: WebGL2RenderingContext): WebGLProgram {
  const program = gl.createProgram();
  if (!program) throw new Error(m.gl_program_create_failed());
  gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, VERTEX_SOURCE));
  gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, FRAGMENT_SOURCE));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error(m.gl_program_link_failed({ log: String(gl.getProgramInfoLog(program)) }));
  }
  return program;
}

function buildQuad(
  gl: WebGL2RenderingContext,
  program: WebGLProgram,
): { vao: WebGLVertexArrayObject; vbo: WebGLBuffer } {
  const vao = gl.createVertexArray();
  const vbo = gl.createBuffer();
  if (!vao || !vbo) throw new Error(m.gl_quad_alloc_failed());
  gl.bindVertexArray(vao);
  gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
  gl.bufferData(gl.ARRAY_BUFFER, 16 * 4, gl.DYNAMIC_DRAW);
  const position = gl.getAttribLocation(program, 'a_imagePos');
  const uv = gl.getAttribLocation(program, 'a_uv');
  gl.enableVertexAttribArray(position);
  gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 16, 0);
  gl.enableVertexAttribArray(uv);
  gl.vertexAttribPointer(uv, 2, gl.FLOAT, false, 16, 8);
  gl.bindVertexArray(null);
  return { vao, vbo };
}
