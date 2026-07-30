// Transform parity: the TypeScript port must return exactly what the Python domain returns.
//
// The reference values are produced by the real `ViewportState`
// (scripts/gen_web_fixtures.py). A port that drifts breaks nothing visible — the image would
// simply be drawn in the wrong place — hence this test.

import { describe, expect, it } from 'vitest';

import { Camera, MAX_ZOOM, MIN_ZOOM, clampZoom } from '../src/viewport/camera';
import transforms from './fixtures/transforms.json';
import zoomPivot from './fixtures/zoom-pivot.json';

function cameraFor(kase: (typeof transforms)['cases'][number]): Camera {
  const [width, height] = transforms.image_size as [number, number];
  const camera = new Camera(width, height);
  camera.updateGeometry(kase.vw, kase.vh, 1);
  camera.setZoom(kase.zoom);
  camera.setCenter(kase.center as [number, number]);
  return camera;
}

describe('Camera — parity with model/viewport_state.py', () => {
  it.each(transforms.cases.map((kase, index) => [index, kase] as const))(
    'case %i: imageToViewport',
    (_index, kase) => {
      const camera = cameraFor(kase);
      kase.points.forEach((point, i) => {
        const got = camera.imageToViewport(point as [number, number]);
        const want = kase.image_to_viewport[i] as [number, number];
        expect(got[0]).toBeCloseTo(want[0], 9);
        expect(got[1]).toBeCloseTo(want[1], 9);
      });
    },
  );

  it.each(transforms.cases.map((kase, index) => [index, kase] as const))(
    'case %i: viewportToImage',
    (_index, kase) => {
      const camera = cameraFor(kase);
      kase.points.forEach((point, i) => {
        const got = camera.viewportToImage(point as [number, number]);
        const want = kase.viewport_to_image[i] as [number, number];
        expect(got[0]).toBeCloseTo(want[0], 9);
        expect(got[1]).toBeCloseTo(want[1], 9);
      });
    },
  );

  it('both transforms are inverses of each other', () => {
    const camera = cameraFor(transforms.cases[0]!);
    for (const point of [
      [0, 0],
      [640.25, 480.5],
      [-31, 1200],
    ] as [number, number][]) {
      const round = camera.viewportToImage(camera.imageToViewport(point));
      expect(round[0]).toBeCloseTo(point[0], 6);
      expect(round[1]).toBeCloseTo(point[1], 6);
    }
  });
});

describe('Camera — zoom about a pivot', () => {
  it.each(zoomPivot.cases.map((kase, index) => [index, kase] as const))(
    'case %i: the pivot point stays put',
    (_index, kase) => {
      const [width, height] = zoomPivot.image_size as [number, number];
      const camera = new Camera(width, height);
      camera.updateGeometry(zoomPivot.vw, zoomPivot.vh, 1);
      camera.setZoom(kase.start_zoom);
      camera.setCenter(kase.center_before as [number, number]);

      const before = camera.imageToViewport(kase.pivot as [number, number]);
      camera.setZoom(kase.target_zoom, kase.pivot as [number, number]);
      const after = camera.imageToViewport(kase.pivot as [number, number]);

      // the computed center must be the domain's…
      expect(camera.center[0]).toBeCloseTo(kase.center_after[0]!, 9);
      expect(camera.center[1]).toBeCloseTo(kase.center_after[1]!, 9);
      // …and the property that justifies the formula must hold: the pivot does not move on screen
      expect(after[0]).toBeCloseTo(before[0], 6);
      expect(after[1]).toBeCloseTo(before[1], 6);
    },
  );
});

describe('Camera — limits and fitting', () => {
  it('clamps zoom the way the domain does', () => {
    expect(clampZoom(1e6)).toBe(MAX_ZOOM);
    expect(clampZoom(0)).toBe(MIN_ZOOM);
    const camera = new Camera(100, 100);
    camera.setZoom(1e6);
    expect(camera.zoom).toBe(MAX_ZOOM);
  });

  it('zoomToFit does not enlarge by default', () => {
    const camera = new Camera(100, 100);
    camera.updateGeometry(1000, 1000, 1);
    camera.zoomToFit();
    expect(camera.zoom).toBe(1);
    camera.zoomToFit(true);
    expect(camera.zoom).toBe(10);
  });

  it('zoomToFit picks the constraining dimension and recenters', () => {
    const camera = new Camera(1200, 800);
    camera.updateGeometry(600, 600, 1);
    camera.zoomToFit();
    expect(camera.zoom).toBeCloseTo(0.5, 9); // 600/1200 < 600/800
    expect(camera.center).toEqual([600, 400]);
  });

  it('screen panning converts to image motion at the zoom scale', () => {
    const camera = new Camera(1000, 1000);
    camera.updateGeometry(500, 500, 1);
    camera.setZoom(2);
    camera.setCenter([500, 500]);
    camera.panByViewport(100, -50);
    expect(camera.center).toEqual([450, 525]);
  });
});

describe('Camera — clip matrix', () => {
  it('projects the image corners onto the expected clip space', () => {
    const camera = cameraFor(transforms.cases[0]!);
    const m = camera.clipMatrix();
    const project = (x: number, y: number): [number, number] => [
      m[0]! * x + m[3]! * y + m[6]!,
      m[1]! * x + m[4]! * y + m[7]!,
    ];
    // The matrix must reproduce imageToViewport followed by the move into clip space.
    for (const point of [
      [0, 0],
      [1200, 800],
      [321.5, 99.25],
    ] as [number, number][]) {
      const viewport = camera.imageToViewport(point);
      const expected: [number, number] = [
        (viewport[0] / camera.vw) * 2 - 1,
        1 - (viewport[1] / camera.vh) * 2,
      ];
      const got = project(point[0], point[1]);
      // Single-precision tolerance, not double: the matrix is a Float32Array because it goes
      // straight into `uniformMatrix3fv`. Demanding 1e-9 here would test the storage type,
      // not the formula.
      expect(got[0]).toBeCloseTo(expected[0], 6);
      expect(got[1]).toBeCloseTo(expected[1], 6);
    }
  });
});
