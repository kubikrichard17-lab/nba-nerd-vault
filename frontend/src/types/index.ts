export interface SeasonStat {
  season_id: string;
  team_abbreviation: string;
  player_age: number;
  gp: number;
  gs: number;
  min_per_game: number;
  pts: number;
  reb: number;
  ast: number;
  stl: number;
  blk: number;
  tov: number;
  pf: number;
  fgm: number;
  fga: number;
  fg_pct: number;
  fg3m: number;
  fg3a: number;
  fg3_pct: number;
  ftm: number;
  fta: number;
  ft_pct: number;
  poss100_pts: number;
  poss100_reb: number;
  poss100_ast: number;
  poss100_stl: number;
  poss100_blk: number;
  poss100_tov: number;
}

export interface PlayerAwardItem {
  description: string;
  description_cs: string;
  count: number;
  season?: string;
}

export interface CareerSummary {
  gp: number;
  pts: number;
  reb: number;
  ast: number;
  stl: number;
  blk: number;
  tov: number;
  fg_pct: number;
  fg3_pct: number;
  ft_pct: number;
  poss100_pts: number;
  poss100_reb: number;
  poss100_ast: number;
  poss100_stl: number;
  poss100_blk: number;
}

/** Pobyt hráče v jednom klubu (klub + roky + průměry) */
export interface ClubCareer {
  team_abbreviation: string;
  team_name: string;
  from_season: string;
  to_season: string;
  gp: number;
  pts: number;
  reb: number;
  ast: number;
  stl: number;
  blk: number;
  fg3m: number;
}

export interface PlayerProfile {
  id: number;
  full_name: string;
  first_name?: string;
  last_name?: string;
  is_active: boolean;
  headshot_url?: string;
  height_cm?: number;
  height_ft?: string;
  weight_kg?: number;
  weight_lbs?: number;
  position?: string;
  draft_year?: string;
  draft_round?: string;
  draft_number?: string;
  draft_team?: string;
  college?: string;
  country?: string;
  bio_summary?: string;
  scouting_report?: string;
  playstyle_tags: string[];
  season_stats: SeasonStat[];
  career_summary: CareerSummary;
  /** Kariéra po klubech – kteří klubech, v jakých letech a s jakými čísly */
  clubs?: ClubCareer[];
  awards: PlayerAwardItem[];
  latest_season?: SeasonStat;
}

export interface ClosestBreakdown {
  herni_styl: string;
  fyzicko: string;
  statisticky_dopad: string;
}

export interface ClosestAlternative {
  id: number;
  full_name: string;
  match_pct: number;
  role_label: string;
}

/** Kandidát, kterého AI vypsala do top_3_candidates */
export interface ClosestCandidate {
  id: number;
  name: string;
  why: string;
}

export interface ClosestPlayer {
  id: number;
  full_name: string;
  position?: string;
  role_label?: string;
  headshot_url?: string;
  is_active?: boolean;
  match_pct: number;
  physical_pct: number;
  statistical_pct: number;
  stylistic_pct: number;
  style_pct?: number;
  stats_pct?: number;
  playstyle_tags?: string[];
  summary_cs?: string;
}

/** Jedna fáze kariéry – raná nebo pozdní – s vlastním nejbližším hráčem. */
export interface CareerPhaseInfo {
  key: 'early' | 'late' | string;
  label: string;
  season?: string;
  seasons?: string[];
  range?: string;
  gp?: number;
}

/** Srovnání pro jednu fázi kariéry (stejná struktura jako celek). */
export interface CareerPhaseResult extends ClosestResponse {
  phase: CareerPhaseInfo;
}

/** Z jakých sezón se počítá vrcholná verze hráče. */
export interface PrimeInfo {
  label: string;
  season?: string;
  seasons?: string[];
}

export interface ClosestResponse {
  player_id?: number;
  player_name?: string;
  player_role?: string;
  closest: ClosestPlayer | null;
  reasoning?: string | null;
  match_percentage?: number;
  breakdown?: ClosestBreakdown | null;
  alternatives?: ClosestAlternative[];
  /** Tři porovnání ze zadání (nová pole) */
  style_comparison?: string;
  physical_comparison?: string;
  stats_comparison?: string;
  /** Kandidáti v pořadí, jak je vypsala AI */
  top_3_candidates?: ClosestCandidate[];
  player_tier?: string;
  weights?: { style: number; physical: number; stats: number };
  ai_used?: boolean;
  /** Vrchol kariéry, ze kterého se výchozí srovnání počítá */
  prime?: PrimeInfo;
  /** 'prime' | 'early' | 'late' */
  basis?: string;
  /** Změnil hráč během kariéry zásadně styl? */
  has_major_evolution?: boolean;
  /** Co se konkrétně změnilo (česky, čísly) */
  evolution_note?: string;
  /** Srovnání pro ranou a pozdní fázi – jen když se hráč proměnil */
  career_phases?: CareerPhaseResult[];
  career_profile?: { pts?: number; reb?: number; ast?: number };
}

export interface SearchResultItem {
  id: number;
  full_name: string;
  is_active: boolean;
  in_db: boolean;
  position?: string;
  headshot_url?: string;
}

export interface CompareMetricRow {
  metric: string;
  p1: string | number;
  p2: string | number;
  diff: string | number;
}

export interface ComparePlayerSummary {
  id: number;
  full_name: string;
  position: string;
  height_cm: number;
  weight_kg: number;
  headshot_url: string;
  selected_season: string;
  stat: Record<string, any>;
  available_seasons: { id: string; label: string }[];
}

/** Stejný model podobnosti jako „nejbližší hráč" na hlavní stránce */
export interface StylePlayerSide {
  id: number;
  full_name: string;
  headshot_url?: string;
  archetype: string;
  position: string;
  three_pts_share?: number;
  two_rate?: number;
  ft_pts_share?: number;
}

export interface StyleCompareResult {
  engine_version: number;
  player1: StylePlayerSide;
  player2: StylePlayerSide;
  match_pct: number;
  style_pct: number;
  physical_pct: number;
  stats_pct: number;
  archetype_a: string;
  archetype_b: string;
  position_a: string;
  position_b: string;
  same_archetype: boolean;
  same_position: boolean;
  style_note: string;
}

export interface CompareResponse {
  player1: ComparePlayerSummary;
  player2: ComparePlayerSummary;
  match_pct: number;
  physical_pct: number;
  statistical_pct: number;
  stylistic_pct: number;
  radar: {
    labels: string[];
    p1: Record<string, number>;
    p2: Record<string, number>;
  };
  table: CompareMetricRow[];
  ai_verdict: string;
  /** Volitelné: stejný model jako u „nejbližšího hráče" */
  style?: StyleCompareResult;
}
