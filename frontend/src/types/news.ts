export interface NewsTeamSide {
  abbr: string;
  name: string;
  pts: number;
  wl: string;
  stats: Record<string, number>;
}

export interface NewsGame {
  game_id: string;
  game_date: string;
  home: NewsTeamSide;
  away: NewsTeamSide;
  winner: string;
  margin: number;
}

export interface NewsGamesResponse {
  season: string;
  dates: string[];
  last_game_date: string | null;
  games: NewsGame[];
  source: string;
}

export interface BoxscorePlayer {
  player_id: number;
  name: string;
  team: string;
  position: string;
  starter: boolean;
  minutes: string;
  pts: number;
  reb: number;
  oreb: number;
  dreb: number;
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
  plus_minus: number;
  comment?: string;
}

export interface BoxscoreTeamTotals {
  team: string;
  name: string;
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
}

export interface BoxscoreTeam {
  abbr: string;
  name: string;
  pts: number;
  players: BoxscorePlayer[];
  totals?: BoxscoreTeamTotals;
}

export interface BoxscoreResponse {
  game_id: string;
  teams: BoxscoreTeam[];
  team_totals: BoxscoreTeamTotals[];
  source: string;
}

export interface LeaderStatDef {
  key: string;
  label: string;
  short: string;
  per_game_available: boolean;
}

export interface LeaderTeamDef {
  abbr: string;
  name: string;
}

export interface LeadersMeta {
  stats: LeaderStatDef[];
  teams: LeaderTeamDef[];
  modes: { key: string; label: string }[];
  current_season: string;
  seasons: string[];
}

export interface LeaderRow {
  rank: number;
  player_id: number;
  name: string;
  team: string;
  team_name: string;
  gp: number;
  career_gp?: number;
  seasons?: number;
  season?: string | null;
  season_span?: string;
  value: number;
  total: number;
  per_game: boolean;
}

export interface LeadersResponse {
  mode: string;
  stat: string;
  stat_label: string;
  per_game: boolean;
  season: string;
  team: string | null;
  team_name: string | null;
  title: string;
  note: string;
  rows: LeaderRow[];
  source: string;
}

export interface ScheduleTeam {
  abbr: string;
  name: string;
  wins: number;
  losses: number;
  score: number;
}

export interface ScheduleGame {
  game_id: string;
  status: number;
  status_text: string;
  tipoff_utc: string;
  label: string;
  sublabel: string;
  home: ScheduleTeam;
  away: ScheduleTeam;
}

export interface ScheduleResponse {
  date: string;
  day_offset: number;
  games: ScheduleGame[];
  source: string;
}
