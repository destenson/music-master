/** Shapes the page reads out of the vocabulary and back from the text tier. */

export type Control =
  | "multi_select"
  | "single_select"
  | "numeric_with_descriptor"
  | "key_mode"
  | "combo_free";

export interface Option {
  id: string;
  label: string;
  aliases?: string[];
  excludes?: string[];
}

export interface Bin {
  id: string;
  label: string;
  group: string;
  control: Control;
  priority: number;
  maps_to?: string;
  help?: string;
  caution?: string;
  emits_tag?: boolean;
  polarity?: "positive" | "negative";
  value_emits_tag?: boolean;
  unit?: string;
  range?: { min: number; max: number; step: number };
  max_selections?: number;
  options?: Option[];
  descriptor_options?: Option[];
  key_options?: string[];
  mode_options?: string[];
}

export interface VocabularyFile {
  vocabulary_version: string;
  tag_budget: number;
  render_order: string[];
  bins: Bin[];
}

export interface BinSelection {
  options?: string[];
  value?: number | null;
  text?: string | null;
  key?: string | null;
  mode?: string | null;
}

export type Selections = Record<string, BinSelection | undefined>;

export interface RenderResult {
  tags: string[];
  string: string;
  omitted: string[];
  negatives: string[];
  problems: string[];
  profile: string;
  band: number[];
  budget: number;
}

export interface TimelineRow {
  index: number;
  role: string;
  label: string;
  instrumental: boolean;
  bars: number;
  lines: number;
  rhyme_scheme: string | null;
  start_s: number;
  dur_s: number;
  singable_s: number;
  budget_min: number;
  budget_max: number;
  ceiling: number;
  vocals: string[];
  energy_tags: string[];
  transition_out: string | null;
  budget_fits: boolean;
  sparse: boolean;
  hook: boolean;
}

export interface TimelineTotals {
  bars: number;
  sections: number;
  total_s: number;
  vocal_s: number;
  instrumental_s: number;
  instrumental_sections: number;
  vocal_lines: number;
  budget_min: number;
  budget_max: number;
  ceiling: number;
}

export interface TimelinePlan {
  template_id: string;
  template_name: string;
  bpm: number;
  achieved_s: number | null;
  profile_label: string;
  rows: TimelineRow[];
  totals: TimelineTotals;
}

export interface TemplateSection {
  role: string;
  bars: number;
  lines?: number;
  rhyme_scheme?: string;
  energy?: string;
  hook?: boolean;
  optional?: boolean;
  vocals?: string[];
  energy_tags?: string[];
  transition_out?: string;
}

export interface StructureTemplate {
  id: string;
  name: string;
  notes?: string;
  sections: TemplateSection[];
}

export interface TemplatesFile {
  templates: StructureTemplate[];
  default_syllable_band?: number[];
}

export interface LyricSectionReport {
  tag: string;
  counts: number[];
  phrases: number[][];
  scheme: string;
  scheme_expected?: string | null;
  scheme_match?: number | null;
  internal?: number;
  allit?: number;
  syl_per_bar?: number | null;
}

export interface Conformance {
  matched: { expected: unknown; actual: Record<string, unknown> }[];
  missing: string[];
  extra: string[];
  findings: string[];
}

export interface LyricReport {
  lines: number;
  sections: LyricSectionReport[];
  /** Where each section header sits, paired by index with `sections`. */
  outline: { line: number; role: string }[];
  errors: string[];
  warnings: string[];
  oracle_tasks: string[];
  conformance: Conformance | null;
}

/** The artifacts the render path produces, serialised exactly as they would be written. */
export interface Artifacts {
  prompt: {
    song_id: string;
    seed: number;
    style: { rendered_string: string; rendered_tags: string[] };
    metadata: {
      bpm: number;
      duration_s: number;
      key: string | null;
      mode: string | null;
      timesignature: string;
      language: string;
    };
    form: {
      composition_sha256: string;
      sections: { name: string; bars: number; label: string }[];
    };
    target: { seed: number; graph_ref: string };
    negative: { artist_references: string[] };
  };
  composition: Record<string, unknown>;
  workflow: Record<string, unknown>;
  prompt_sha256: string;
  /** The bytes of each artifact, from the same serialiser the hashes go through. */
  prompt_text: string;
  composition_text: string;
  workflow_text: string;
}

/** One entry from any of the lyric tag pools. */
export interface TagTerm {
  id: string;
  label: string;
  axis?: string;
  description?: string;
  signature?: string;
  instrumental?: boolean;
  numbered?: boolean;
}

export interface SectionTagsFile {
  section_tags_version: string;
  note?: string;
  grammar: {
    section_tag: string;
    max_modifiers: number;
    max_tags_per_section: number;
    max_transitions_per_section: number;
    rules: string[];
  };
  sections: TagTerm[];
  modifiers: TagTerm[];
  transition_tags: TagTerm[];
  vocal_tags: TagTerm[];
  energy_tags: TagTerm[];
  instrumental_section_tags: TagTerm[];
}

/** The pools the grammar lens offers, in the order a section is written. */
export interface TagPools {
  sections: TagTerm[];
  modifiers: TagTerm[];
  transition_tags: TagTerm[];
  vocal_tags: TagTerm[];
  energy_tags: TagTerm[];
  instrumental_section_tags: TagTerm[];
}
