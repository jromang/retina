//! retina._core — compiled image operators (hot path) exposed to Python through PyO3.
//!
//! Key architectural point (cf. ARCHITECTURE.md): the heavy operations release the GIL
//! (`Python::detach`) and parallelize across cores (rayon), so that the GUI never freezes
//! and Python multithreading is real.

use ndarray::{Array2, Array3};
use numpy::{IntoPyArray, PyArray2, PyArray3, PyReadonlyArray2, PyReadonlyArray3};
use pyo3::prelude::*;
use rayon::prelude::*;

/// Normalized 1D Gaussian kernel, radius = ceil(3*sigma).
fn gaussian_kernel(sigma: f32) -> Vec<f32> {
    let radius = (3.0 * sigma).ceil().max(1.0) as isize;
    let mut k: Vec<f32> = (-radius..=radius)
        .map(|i| {
            let x = i as f32;
            (-(x * x) / (2.0 * sigma * sigma)).exp()
        })
        .collect();
    let sum: f32 = k.iter().sum();
    for v in k.iter_mut() {
        *v /= sum;
    }
    k
}

/// Edge reflection (mirror) for an out-of-bounds index.
#[inline]
fn reflect(i: isize, n: isize) -> usize {
    let mut i = i;
    if n == 1 {
        return 0;
    }
    // repeated reflection until the index falls back inside [0, n)
    while i < 0 || i >= n {
        if i < 0 {
            i = -i - 1;
        } else if i >= n {
            i = 2 * n - i - 1;
        }
    }
    i as usize
}

/// Separable 1D convolution along the horizontal axis (x). HWC data in a flat Vec.
fn convolve_h(input: &[f32], h: usize, w: usize, c: usize, k: &[f32]) -> Vec<f32> {
    let radius = (k.len() / 2) as isize;
    let wn = w as isize;
    (0..h)
        .into_par_iter()
        .flat_map(|y| {
            let row_base = y * w * c;
            let mut row = vec![0.0f32; w * c];
            for x in 0..w {
                for ch in 0..c {
                    let mut acc = 0.0f32;
                    for (ki, &kv) in k.iter().enumerate() {
                        let sx = reflect(x as isize + ki as isize - radius, wn);
                        acc += kv * input[row_base + sx * c + ch];
                    }
                    row[x * c + ch] = acc;
                }
            }
            row
        })
        .collect()
}

/// Separable 1D convolution along the vertical axis (y). HWC data in a flat Vec.
fn convolve_v(input: &[f32], h: usize, w: usize, c: usize, k: &[f32]) -> Vec<f32> {
    let radius = (k.len() / 2) as isize;
    let hn = h as isize;
    (0..h)
        .into_par_iter()
        .flat_map(|y| {
            let mut row = vec![0.0f32; w * c];
            for x in 0..w {
                for ch in 0..c {
                    let mut acc = 0.0f32;
                    for (ki, &kv) in k.iter().enumerate() {
                        let sy = reflect(y as isize + ki as isize - radius, hn);
                        acc += kv * input[(sy * w + x) * c + ch];
                    }
                    row[x * c + ch] = acc;
                }
            }
            row
        })
        .collect()
}

/// Separable Gaussian convolution of an (H, W, C) float32 image.
///
/// Returns a new numpy array. The computation releases the GIL.
#[pyfunction]
fn gaussian_convolve<'py>(
    py: Python<'py>,
    arr: PyReadonlyArray3<'py, f32>,
    sigma: f32,
) -> PyResult<Bound<'py, PyArray3<f32>>> {
    let view = arr.as_array();
    let (h, w, c) = (view.shape()[0], view.shape()[1], view.shape()[2]);
    // contiguous copy in logical C order (HWC), whatever the input memory layout
    let input: Vec<f32> = view.iter().copied().collect();

    if sigma <= 0.0 {
        let out = Array3::from_shape_vec((h, w, c), input)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        return Ok(out.into_pyarray(py));
    }

    let result = py.detach(move || {
        let k = gaussian_kernel(sigma);
        let tmp = convolve_h(&input, h, w, c, &k);
        convolve_v(&tmp, h, w, c, &k)
    });

    let out = Array3::from_shape_vec((h, w, c), result)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    Ok(out.into_pyarray(py))
}

// ---------------------------------------------------------------------------
// TGV² (Bredies-Kunisch-Pock) by primal-dual — port of the measured hot spot.
//
// The only GO out of profiling (`scripts/profile_hotspots.py`: ~229 s at 24 Mpx, 94% of the
// time inside the numpy loops of `denoise.py::_tgv_denoise_channel`). A like-for-like port:
// same forward/backward differences, same edge rules, f64 internally — numerical parity with
// the numpy path is tested to within 1e-6. The numpy fallback stays in `denoise.py` for
// machines without the compiled extension.

/// Forward gradient in x: `g[i,j] = u[i,j+1] - u[i,j]`, 0 on the last column.
#[inline]
fn fgrad_x(u: &[f64], i: usize, j: usize, w: usize) -> f64 {
    if j + 1 < w {
        u[i * w + j + 1] - u[i * w + j]
    } else {
        0.0
    }
}

/// Forward gradient in y: `g[i,j] = u[i+1,j] - u[i,j]`, 0 on the last row.
#[inline]
fn fgrad_y(u: &[f64], i: usize, j: usize, w: usize, h: usize) -> f64 {
    if i + 1 < h {
        u[(i + 1) * w + j] - u[i * w + j]
    } else {
        0.0
    }
}

/// Divergence in x (adjoint, up to a sign, of the forward gradient): backward difference.
#[inline]
fn bdiv_x(p: &[f64], i: usize, j: usize, w: usize) -> f64 {
    if j == 0 {
        p[i * w]
    } else if j == w - 1 {
        -p[i * w + w - 2]
    } else {
        p[i * w + j] - p[i * w + j - 1]
    }
}

/// Divergence in y: backward difference with the same edge rules.
#[inline]
fn bdiv_y(p: &[f64], i: usize, j: usize, w: usize, h: usize) -> f64 {
    if i == 0 {
        p[j]
    } else if i == h - 1 {
        -p[(h - 2) * w + j]
    } else {
        p[i * w + j] - p[(i - 1) * w + j]
    }
}

/// One complete run of the TGV² primal-dual on an (h, w) channel held in a flat Vec.
fn tgv_channel(
    f: &[f64],
    h: usize,
    w: usize,
    alpha1: f64,
    alpha0: f64,
    iterations: u32,
) -> Vec<f64> {
    let n = h * w;
    let tau = 1.0 / 12.0f64.sqrt();
    let sigma = tau;

    let mut u = f.to_vec();
    let mut wx = vec![0.0f64; n];
    let mut wy = vec![0.0f64; n];
    let mut px = vec![0.0f64; n];
    let mut py = vec![0.0f64; n];
    let mut qxx = vec![0.0f64; n];
    let mut qyy = vec![0.0f64; n];
    let mut qxy = vec![0.0f64; n];
    let mut ub = u.clone();
    let mut wxb = wx.clone();
    let mut wyb = wy.clone();
    // buffers of the primal phase (swapped with the current ones at each iteration)
    let mut u2 = vec![0.0f64; n];
    let mut wx2 = vec![0.0f64; n];
    let mut wy2 = vec![0.0f64; n];
    let mut ub2 = vec![0.0f64; n];
    let mut wxb2 = vec![0.0f64; n];
    let mut wyb2 = vec![0.0f64; n];

    for _ in 0..iterations {
        // --- dual: p (on ∇ū - w̄), projected into the ball of radius α1 ---
        px.par_chunks_mut(w)
            .zip(py.par_chunks_mut(w))
            .enumerate()
            .for_each(|(i, (px_row, py_row))| {
                for j in 0..w {
                    let idx = i * w + j;
                    let mut vx = px_row[j] + sigma * (fgrad_x(&ub, i, j, w) - wxb[idx]);
                    let mut vy = py_row[j] + sigma * (fgrad_y(&ub, i, j, w, h) - wyb[idx]);
                    let norm = (1.0f64).max((vx * vx + vy * vy).sqrt() / alpha1);
                    vx /= norm;
                    vy /= norm;
                    px_row[j] = vx;
                    py_row[j] = vy;
                }
            });
        // --- dual: q (on E(w̄)), projected into the ball of radius α0 ---
        qxx.par_chunks_mut(w)
            .zip(qyy.par_chunks_mut(w))
            .zip(qxy.par_chunks_mut(w))
            .enumerate()
            .for_each(|(i, ((qxx_row, qyy_row), qxy_row))| {
                for j in 0..w {
                    let mut vxx = qxx_row[j] + sigma * fgrad_x(&wxb, i, j, w);
                    let mut vyy = qyy_row[j] + sigma * fgrad_y(&wyb, i, j, w, h);
                    let mut vxy = qxy_row[j]
                        + sigma * 0.5 * (fgrad_y(&wxb, i, j, w, h) + fgrad_x(&wyb, i, j, w));
                    let nq =
                        (1.0f64).max((vxx * vxx + vyy * vyy + 2.0 * vxy * vxy).sqrt() / alpha0);
                    vxx /= nq;
                    vyy /= nq;
                    vxy /= nq;
                    qxx_row[j] = vxx;
                    qyy_row[j] = vyy;
                    qxy_row[j] = vxy;
                }
            });
        // --- primal + extrapolation, fused row by row ---
        u2.par_chunks_mut(w)
            .zip(wx2.par_chunks_mut(w))
            .zip(wy2.par_chunks_mut(w))
            .zip(ub2.par_chunks_mut(w))
            .zip(wxb2.par_chunks_mut(w))
            .zip(wyb2.par_chunks_mut(w))
            .enumerate()
            .for_each(
                |(i, (((((u_row, wx_row), wy_row), ub_row), wxb_row), wyb_row))| {
                    for j in 0..w {
                        let idx = i * w + j;
                        let div_p = bdiv_x(&px, i, j, w) + bdiv_y(&py, i, j, w, h);
                        let un = (u[idx] + tau * div_p + tau * f[idx]) / (1.0 + tau);
                        // (E^T q) — div = -adjoint of ∇, same signs as the numpy path
                        let sym_x = bdiv_x(&qxx, i, j, w) + 0.5 * bdiv_y(&qxy, i, j, w, h);
                        let sym_y = bdiv_y(&qyy, i, j, w, h) + 0.5 * bdiv_x(&qxy, i, j, w);
                        let wxn = wx[idx] + tau * (px[idx] + sym_x);
                        let wyn = wy[idx] + tau * (py[idx] + sym_y);
                        u_row[j] = un;
                        wx_row[j] = wxn;
                        wy_row[j] = wyn;
                        ub_row[j] = 2.0 * un - u[idx];
                        wxb_row[j] = 2.0 * wxn - wx[idx];
                        wyb_row[j] = 2.0 * wyn - wy[idx];
                    }
                },
            );
        std::mem::swap(&mut u, &mut u2);
        std::mem::swap(&mut wx, &mut wx2);
        std::mem::swap(&mut wy, &mut wy2);
        std::mem::swap(&mut ub, &mut ub2);
        std::mem::swap(&mut wxb, &mut wxb2);
        std::mem::swap(&mut wyb, &mut wyb2);
    }
    u
}

/// TGV² denoising of an (H, W) float64 channel — cf. `denoise.py::_tgv_denoise_channel`.
///
/// Returns a new numpy array. The computation releases the GIL and parallelizes by rows.
#[pyfunction]
fn tgv_denoise<'py>(
    py: Python<'py>,
    arr: PyReadonlyArray2<'py, f64>,
    alpha1: f64,
    alpha0: f64,
    iterations: u32,
) -> PyResult<Bound<'py, PyArray2<f64>>> {
    let view = arr.as_array();
    let (h, w) = (view.shape()[0], view.shape()[1]);
    if h < 2 || w < 2 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "tgv_denoise : image trop petite (min 2×2)",
        ));
    }
    let input: Vec<f64> = view.iter().copied().collect();
    let result = py.detach(move || tgv_channel(&input, h, w, alpha1, alpha0, iterations));
    let out = Array2::from_shape_vec((h, w), result)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    Ok(out.into_pyarray(py))
}

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__doc__", "Retina native core operators")?;
    m.add_function(wrap_pyfunction!(gaussian_convolve, m)?)?;
    m.add_function(wrap_pyfunction!(tgv_denoise, m)?)?;
    Ok(())
}
