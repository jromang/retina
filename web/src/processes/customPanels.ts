// Registry of custom process panels.
//
// The form auto-generated from `Process.parameters` covers almost the whole catalogue. A few
// processes have a setting that does not fit in a field — placing samples on the image,
// scrolling through a sequence, reading the histogram one is in the middle of transforming.
// They declare a component here, rendered **above** the form, which adds to the fields without
// replacing them.
//
// The registry was a single `if` as long as there was only one case; the table arrives with
// the fourth, not before. The panels import the type from here with `import type`: the import
// is erased at compile time, so the table can import them back without a runtime cycle.

import type { JSX } from 'preact';

export interface CustomPanelProps {
  processId: string;
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
}

export type CustomPanel = (props: CustomPanelProps) => JSX.Element;

/** Custom panel of a process, or `null` if it has none. */
export function customPanelFor(processId: string): CustomPanel | null {
  return PANELS[processId] ?? null;
}

// Import after the type declaration: these modules depend on us only for types.
import { BlinkPanel } from './BlinkPanel';
import { DbeSamples } from './DbePanel';
import { CloneStampTool } from './CloneStampPanel';
import { DynamicAlignmentTool } from './DynamicAlignmentPanel';
import { DynamicCropTool } from './DynamicCropPanel';
import { DynamicPsfTool } from './DynamicPsfPanel';
import { HistogramPanel } from './HistogramPanel';

const PANELS: Record<string, CustomPanel> = {
  DynamicBackgroundExtraction: DbeSamples,
  Blink: BlinkPanel,
  // The four "dynamic" tools: their setting IS a gesture on the image, and their scriptable
  // core simply expects coordinates.
  DynamicCrop: DynamicCropTool,
  CloneStamp: CloneStampTool,
  DynamicPSF: DynamicPsfTool,
  DynamicAlignment: DynamicAlignmentTool,
  // Setting a tone curve without seeing the distribution being deformed is a blind exercise:
  // these processes transform precisely what the histogram shows.
  HistogramTransformation: HistogramPanel,
  CurvesTransformation: HistogramPanel,
  GeneralizedHyperbolicStretch: HistogramPanel,
};
