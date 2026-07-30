// Generalized hyperbolic stretch — TypeScript mirror of
// `processes/stretch.py::ghs_transfer`.
//
// The histogram panel plots the curve the domain will apply. If the two diverge, nothing
// breaks: the curve displayed simply stops describing the result, which is worse than an
// outright error. Hence this **identical** port, and the parity fixture produced by the domain
// (`web/tests/ghs.test.ts`).
//
// The equations are those of the published reference documentation of the GHS module; the
// comments that explain *why* they are written this way (unequal scales between sub-families,
// always-positive argument) are on the Python side, at the source.

const GHS_EPS = 1e-9;

/** `T(u)` and `T'(u)` of the base equations, for `u ≥ 0`. */
function base(u: number, d: number, b: number): [number, number] {
  if (Math.abs(b + 1) < GHS_EPS) return [Math.log1p(d * u), d / (1 + d * u)];
  if (b < 0) {
    const w = Math.log1p(-b * d * u);
    return [(1 - Math.exp(((b + 1) / b) * w)) / (d * (b + 1)), Math.exp(w / b)];
  }
  if (b < GHS_EPS) {
    const e = Math.exp(-d * u);
    return [1 - e, d * e];
  }
  const w = Math.log1p(b * d * u);
  return [1 - Math.exp(-w / b), d * Math.exp(-((1 + b) / b) * w)];
}

/** `InvT(y)`, the inverse of {@link base}. */
function inverseBase(y: number, d: number, b: number): number {
  if (Math.abs(b + 1) < GHS_EPS) return Math.expm1(y) / d;
  if (b < 0) {
    const w = Math.log1p(Math.max(-(b + 1) * d * y, -1 + 1e-12));
    return (1 - Math.exp((b / (b + 1)) * w)) / (d * b);
  }
  const reste = Math.log1p(-Math.min(y, 1 - 1e-12));
  if (b < GHS_EPS) return -reste / d;
  return Math.expm1(-b * reste) / (b * d);
}

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);

export interface GhsParameters {
  stretchFactor: number;
  localIntensity: number;
  symmetryPoint: number;
  protectShadows: number;
  protectHighlights: number;
  invert?: boolean;
}

/** The GHS transfer function, as the domain will apply it. */
export function ghsTransfer(x: number, p: GhsParameters): number {
  const d = Math.expm1(p.stretchFactor);
  if (!(d > 0)) return clamp(x, 0, 1);
  const b = p.localIntensity;
  const sp = clamp(p.symmetryPoint, 0, 1);
  const lp = clamp(p.protectShadows, 0, sp);
  const hp = clamp(p.protectHighlights, sp, 1);

  const [t2Lp0, t2pLp] = base(sp - lp, d, b);
  const t2Lp = -t2Lp0;
  const [t3Hp, t3pHp] = base(hp - sp, d, b);
  const t10 = t2pLp * (0 - lp) + t2Lp;
  const t41 = t3pHp * (1 - hp) + t3Hp;
  const etendue = t41 - t10;
  if (!Number.isFinite(etendue) || Math.abs(etendue) < 1e-15) return clamp(x, 0, 1);

  if (!p.invert) {
    let y: number;
    if (x < lp) y = t2pLp * (x - lp) + t2Lp;
    else if (x < sp) y = -base(Math.max(sp - x, 0), d, b)[0];
    else if (x < hp) y = base(Math.max(x - sp, 0), d, b)[0];
    else y = t3pHp * (x - hp) + t3Hp;
    return clamp((y - t10) / etendue, 0, 1);
  }

  const xp = t10 + x * etendue;
  let y: number;
  if (x < (t2Lp - t10) / etendue) y = lp + (xp - t2Lp) / t2pLp;
  else if (x < (0 - t10) / etendue) y = sp - inverseBase(Math.max(-xp, 0), d, b);
  else if (x < (t3Hp - t10) / etendue) y = sp + inverseBase(Math.max(xp, 0), d, b);
  else y = hp + (xp - t3Hp) / t3pHp;
  return clamp(y, 0, 1);
}
