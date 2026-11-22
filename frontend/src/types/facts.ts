export interface FactBio {
  birthdate: string;
  age: number | null;
  from_year: number | null;
  to_year: number | null;
  team: string;
  position: string;
  height: string;
}

export interface Fact {
  id: string;
  player_id: number;
  player: string;
  category: string;
  text: string;
  headshot_url: string;
  bio: FactBio;
}

export interface FactsResponse {
  count: number;
  total: number;
  categories: string[];
  facts: Fact[];
}
