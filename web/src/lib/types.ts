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
  /** Observations that are neither defects nor work for the oracle, e.g. a lenient rhyme landing. */
  notes: string[];
  oracle_tasks: string[];
  conformance: Conformance | null;
}

/**
 * A writing-brief directive the lyric repair took out of a generated draft.
 *
 * The brief is a contract, and a model sometimes copies one of its lines — `Energy 3/5` — into the
 * section it describes. The repair is exact, and this is the record of what it removed.
 */
export interface DirectiveRemoval {
  /** The line number in the draft as the model wrote it. */
  line: number;
  /** Which brief template the line matched, e.g. `energy`. */
  kind: string;
  /** The removed line, trimmed. */
  text: string;
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

/**
 * A radio station: a fixed identity plus the pools a song draws its sound from.
 *
 * The pools are what make consecutive songs differ without leaving the genre — a station is a
 * range, not an arrangement. The planner computes tempo, structure and key, so they are not in
 * `fixed`.
 */
export interface RadioStation {
  id: string;
  name: string;
  family: string;
  tagline: string;
  template_id: string;
  structure_option?: string;
  bpm: number | number[] | { min: number; max: number };
  themes: string[];
  keys?: { key: string; mode: string }[];
  fixed: Record<string, string[]>;
  pools: Record<string, { from: string[]; count?: [number, number] }>;
}

export interface RadioStationsFile {
  radio_stations_version: string;
  note?: string;
  stations: RadioStation[];
}

/** One requirement's verdict, as `schemas/compliance-report.schema.json` describes it. */
export type ComplianceVerdictValue = "met" | "unmet" | "uncertain" | "unverified";

export type EvidenceClass = "measurement" | "description" | "self_report" | "oracle" | "transcription";

export type EnforcementMode =
  | "enforced"
  | "verified"
  | "conditioned + verified"
  | "measured"
  | "unverified";

/** One piece of evidence behind a verdict, each item carrying its own class and source. */
export interface ComplianceEvidence {
  class: EvidenceClass;
  source: string;
  value?: unknown;
  threshold?: number | null;
  note?: string | null;
}

export interface ComplianceVerdict {
  requirement_id: string;
  text?: string;
  severity?: "hard" | "soft" | "policy";
  /** The `verify` field from the spec, echoed so the report shows who decided. */
  checker: string;
  verdict: ComplianceVerdictValue;
  probability?: number | null;
  confidence?: number | null;
  top2_margin?: number | null;
  enforcement?: EnforcementMode | null;
  evidence_class?: EvidenceClass | null;
  supported_by?: ComplianceEvidence[];
  note?: string | null;
  /**
   * What to change, for a verdict that did not pass. Written in code from the requirement and the
   * measured failure, never by the model, so it cannot drift from what was actually checked.
   */
  suggestion?: string | null;
  /** The same fix as an imperative a lyric generator can act on; absent for a caption problem. */
  repair_instruction?: string | null;
  measured?: {
    value?: unknown;
    target?: unknown;
    within_tolerance?: boolean;
  } | null;
  evidence?: string[];
}

export type ComplianceOverall =
  | "compliant"
  | "compliant_with_unmet_soft"
  | "non_compliant"
  | "unverified";

export interface ComplianceCounts {
  met?: number;
  total?: number;
  /** Met verdicts resting on arithmetic or signal processing. The number to trust. */
  decided_by_measurement?: number;
  /** Met verdicts resting on a model's generated account. The number to watch. */
  decided_by_description?: number;
  uncertain?: number;
  unverified?: number;
}

/** The summary question, reported alongside the individual verdicts rather than as a substitute. */
export interface ComplianceCrossCheck {
  noul?: number | null;
  fired?: boolean;
  agrees_with_individual_verdicts?: boolean;
  note?: string | null;
}

export interface ComplianceOracle {
  kind: "jev" | "local" | "replay" | "none";
  model: string | null;
  reachable: boolean;
  /** Set when the oracle failed and semantic checks fell back to unverified. */
  degraded_reason?: string | null;
}

export interface ComplianceReport {
  report_version: "1";
  song_id: string;
  generated_at?: string;
  oracle: ComplianceOracle;
  artifacts?: {
    audio_path?: string | null;
    lyrics_path?: string | null;
    midi_path?: string | null;
    fact_sheet_path?: string | null;
  };
  verdicts: ComplianceVerdict[];
  overall: ComplianceOverall;
  /** The report as one paragraph a person reads first: what holds, what does not, and what to do. */
  summary?: string | null;
  /** Explicitly what could not be satisfied; never empty when `overall` is not compliant. */
  unmet?: string[];
  counts?: ComplianceCounts;
  cross_check?: ComplianceCrossCheck;
  /** How many repair rounds ran before this candidate was returned. */
  iterations?: number;
}

/** The body `jev_request` builds and the transport posts to `/v1/systemone`. */
export interface JevRequest {
  state: unknown;
  model: string;
  questions: Record<string, unknown>;
}

/**
 * A verdict code and audio checkers already produced. The battery does not recompute mechanical
 * requirements, so the page reports the ones it can decide itself rather than leaving them to the
 * oracle or silently unverified.
 */
export interface MechanicalVerdict {
  requirement_id: string;
  verdict: string;
  checker?: string;
  severity?: string;
}

/** One song of one station, as `musicmaster.radio.plan_song` returns it. */
export interface RadioPlan {
  station_id: string;
  station_name: string;
  song_id: string;
  title: string;
  template_id: string;
  bpm: number;
  selections: Selections;
  theme: string;
  instrumental: boolean;
  /** Where the take's companion files belong. Keyed by the song, not by the kind of take. */
  artifacts_dir: string;
  /** The audio's path under ComfyUI's output directory; an instrumental take says so in the name. */
  filename_prefix: string;
}
