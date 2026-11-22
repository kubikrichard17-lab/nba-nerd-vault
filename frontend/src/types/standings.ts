export interface FormGame {
  game_id: string;
  date: string;
  wl: string;
  pts: number;
  opp_pts: number | null;
  matchup: string;
  opponent: string;
  home: boolean;
}

export interface StandingsTeam {
  team_id: number;
  abbr: string;
  name: string;
  conference: 'East' | 'West';
  division: string;
  rank: number;
  seed: number;
  wins: number;
  losses: number;
  win_pct: number;
  games_back: number;
  conf_record: string;
  home: string;
  road: string;
  l10: string;
  streak: string;
  ppg: number;
  opp_ppg: number;
  diff: number;
  form: FormGame[];
}

export interface StandingsResponse {
  season: string;
  east: StandingsTeam[];
  west: StandingsTeam[];
  updated: string;
  source: string;
}
