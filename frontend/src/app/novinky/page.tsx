'use client';

import React, { useEffect, useState } from 'react';
import {
  ChevronDown,
  Loader2,
  AlertCircle,
  CalendarDays,
  Trophy,
  Users,
  Clock,
  Radio,
  CalendarClock,
} from 'lucide-react';
import type {
  BoxscorePlayer,
  BoxscoreResponse,
  NewsGame,
  NewsGamesResponse,
  ScheduleGame,
  ScheduleResponse,
  ScheduleTeam,
} from '@/types/news';
import { API } from '@/lib/api';


const pct = (v: number) => `${Math.round((v || 0) * 1000) / 10}%`;

const fmtDate = (s: string) => {
  try {
    const d = new Date(`${s}T12:00:00`);
    if (isNaN(d.getTime())) return s;
    return d.toLocaleDateString('cs-CZ', { day: 'numeric', month: 'long', year: 'numeric' });
  } catch {
    return s;
  }
};

const fmtDateTime = (s: string) => {
  try {
    const d = new Date(s);
    if (isNaN(d.getTime())) return s;
    return d.toLocaleDateString('cs-CZ', { day: 'numeric', month: 'numeric', year: 'numeric' });
  } catch {
    return s;
  }
};

const headshot = (id: number) => `https://cdn.nba.com/headshots/nba/latest/260x190/${id}.png`;

/** Tabulka hráčů jednoho týmu */
function BoxScoreTable({
  teamAbbr,
  players,
}: {
  teamAbbr: string;
  players: BoxscorePlayer[];
}) {
  const th = 'px-2 py-1.5 text-right font-semibold text-slate-400 whitespace-nowrap';
  const td = 'px-2 py-1.5 text-right whitespace-nowrap tabular-nums';

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px] sm:text-xs">
        <thead className="bg-slate-950/70 border-b border-slate-800">
          <tr>
            <th className="px-2 py-1.5 text-left font-semibold text-slate-400">Hráč</th>
            <th className={th}>MIN</th>
            <th className={th}>PTS</th>
            <th className={th}>REB</th>
            <th className={th}>AST</th>
            <th className={th}>STL</th>
            <th className={th}>BLK</th>
            <th className={th}>TO</th>
            <th className={th}>FG</th>
            <th className={th}>3P</th>
            <th className={th}>FT</th>
            <th className={th}>+/-</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-900">
          {players.map((p) => (
            <tr key={`${p.player_id}-${p.name}`} className="hover:bg-slate-900/60 transition-colors">
              <td className="px-2 py-1.5 text-left">
                <div className="flex items-center gap-2 min-w-0">
                  <img
                    src={headshot(p.player_id)}
                    alt={p.name}
                    className="w-6 h-6 rounded-full object-cover bg-slate-800 shrink-0"
                    onError={(e) => {
                      (e.target as HTMLImageElement).style.visibility = 'hidden';
                    }}
                  />
                  <span className="font-semibold text-white truncate max-w-[9rem] sm:max-w-none">
                    {p.name}
                  </span>
                  {p.position && (
                    <span className="text-[10px] text-slate-500 font-mono">{p.position}</span>
                  )}
                  {p.comment && (
                    <span className="text-[10px] text-amber-500/80">{p.comment}</span>
                  )}
                </div>
              </td>
              <td className={`${td} text-slate-400`}>{p.minutes}</td>
              <td className={`${td} font-bold text-orange-400`}>{p.pts}</td>
              <td className={td}>{p.reb}</td>
              <td className={td}>{p.ast}</td>
              <td className={td}>{p.stl}</td>
              <td className={td}>{p.blk}</td>
              <td className={td}>{p.tov}</td>
              <td className={`${td} text-slate-400`}>
                {p.fgm}/{p.fga}
              </td>
              <td className={`${td} text-slate-400`}>
                {p.fg3m}/{p.fg3a}
              </td>
              <td className={`${td} text-slate-400`}>
                {p.ftm}/{p.fta}
              </td>
              <td
                className={`${td} font-semibold ${
                  p.plus_minus > 0
                    ? 'text-emerald-400'
                    : p.plus_minus < 0
                    ? 'text-red-400'
                    : 'text-slate-400'
                }`}
              >
                {p.plus_minus > 0 ? '+' : ''}
                {p.plus_minus}
              </td>
            </tr>
          ))}
          {players.length === 0 && (
            <tr>
              <td colSpan={12} className="px-2 py-4 text-center text-slate-500 italic">
                Žádní hráči k dispozici.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <p className="px-2 py-1 text-[10px] text-slate-600">
        Tým: <span className="font-mono text-slate-400">{teamAbbr}</span> · kliknutím na tým výše
        přepneš soupisku
      </p>
    </div>
  );
};

/** Rozbalovací detail jednoho zápasu */
function GamePanel({
  game,
  onClose,
}: {
  game: { game_id: string; home: { abbr: string }; away: { abbr: string } };
  onClose: () => void;
}) {
  const [data, setData] = useState<BoxscoreResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTeam, setActiveTeam] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    fetch(`${API}/api/news/games/${game.game_id}`)
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || 'Boxscore se nepodařilo načíst.');
        }
        return res.json();
      })
      .then((d: BoxscoreResponse) => {
        if (!alive) return;
        setData(d);
        setActiveTeam(d.teams[0]?.abbr ?? null);
      })
      .catch((e) => alive && setError(e.message || 'Chyba připojení k backendu.'))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [game.game_id]);

  const active = data?.teams.find((t) => t.abbr === activeTeam) ?? data?.teams[0];

  return (
    <div className="mt-3 rounded-xl border border-slate-800 bg-slate-950/60 p-3 space-y-3">
      {loading && (
        <div className="flex items-center justify-center gap-2 py-6 text-sm text-slate-400">
          <Loader2 className="w-4 h-4 animate-spin text-orange-500" />
          Načítám statistiky zápasu z NBA API…
        </div>
      )}

      {error && !loading && (
        <div className="flex items-center gap-2 p-3 rounded-lg bg-red-950/40 border border-red-800/70 text-xs text-red-200">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      {!loading && !error && data && (
        <>
          {/* Přepínač týmů */}
          <div className="flex flex-wrap items-center gap-2">
            {data.teams.map((t) => {
              const isActive = active?.abbr === t.abbr;
              return (
                <button
                  key={t.abbr}
                  onClick={() => setActiveTeam(t.abbr)}
                  className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-bold border transition-all ${
                    isActive
                      ? 'bg-orange-500 text-white border-orange-400 shadow-md shadow-orange-500/20'
                      : 'bg-slate-900 text-slate-300 border-slate-800 hover:border-orange-500/40'
                  }`}
                >
                  <Users className="w-3.5 h-3.5" />
                  {t.name}
                  <span className={isActive ? 'text-white/90' : 'text-slate-500'}>{t.pts}</span>
                </button>
              );
            })}
            <button
              onClick={onClose}
              className="ml-auto px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-400 hover:text-white bg-slate-900 border border-slate-800"
            >
              Zavřít detail
            </button>
          </div>

          {/* Týmové součty */}
          {active?.totals && (
            <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2">
              {[
                { label: 'FG', value: `${active.totals.fgm}/${active.totals.fga}`, sub: pct(active.totals.fg_pct) },
                { label: '3P', value: `${active.totals.fg3m}/${active.totals.fg3a}`, sub: pct(active.totals.fg3_pct) },
                { label: 'FT', value: `${active.totals.ftm}/${active.totals.fta}`, sub: pct(active.totals.ft_pct) },
                { label: 'Doskoky', value: active.totals.reb, sub: '' },
                { label: 'Asistence', value: active.totals.ast, sub: '' },
                { label: 'Zisky', value: active.totals.stl, sub: '' },
                { label: 'Bloky', value: active.totals.blk, sub: '' },
                { label: 'Ztráty', value: active.totals.tov, sub: '' },
              ].map((box) => (
                <div
                  key={box.label}
                  className="rounded-lg bg-slate-900 border border-slate-800 px-2 py-1.5 text-center"
                >
                  <div className="text-[10px] uppercase tracking-wider text-slate-500">
                    {box.label}
                  </div>
                  <div className="text-sm font-bold text-white tabular-nums">{box.value}</div>
                  {box.sub && <div className="text-[10px] text-slate-400">{box.sub}</div>}
                </div>
              ))}
            </div>
          )}

          {active && <BoxScoreTable teamAbbr={active.abbr} players={active.players} />}
        </>
      )}
    </div>
  );
};

/** Karta jednoho zápasu */
function GameCard({ game }: { game: NewsGame }) {
  const [open, setOpen] = useState(false);
  const homeWon = game.winner === game.home.abbr;

  const side = (s: typeof game.home, isWinner: boolean) => (
    <div className="flex items-center justify-between gap-3">
      <div className="flex items-center gap-2 min-w-0">
        <span
          className={`w-1.5 h-8 rounded-full ${isWinner ? 'bg-orange-500' : 'bg-slate-800'}`}
        />
        <div className="min-w-0">
          <div
            className={`text-sm font-bold truncate ${isWinner ? 'text-white' : 'text-slate-400'}`}
          >
            {s.name}
          </div>
          <div className="text-[10px] font-mono text-slate-500">{s.abbr}</div>
        </div>
      </div>
      <div
        className={`text-xl font-black tabular-nums ${
          isWinner ? 'text-orange-400' : 'text-slate-500'
        }`}
      >
        {s.pts}
      </div>
    </div>
  );

  return (
    <div
      id={`game-${game.game_id}`}
      className="rounded-2xl bg-slate-900/90 border border-slate-800 hover:border-orange-500/30 transition-colors p-4"
    >
      <div className="flex items-center justify-between mb-3">
        <span className="inline-flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-500">
          <CalendarDays className="w-3 h-3" />
          {fmtDate(game.game_date)}
        </span>
        <span className="text-[10px] font-mono text-slate-600">{game.game_id}</span>
      </div>

      <div className="space-y-2">
        {side(game.home, homeWon)}
        {side(game.away, !homeWon)}
      </div>

      <div className="mt-3 flex items-center justify-between">
        <span className="text-[11px] text-slate-500">
          {game.margin === 0 ? 'Remíza' : `Výhra o ${game.margin} b.`}
        </span>
        <button
          onClick={() => setOpen((v) => !v)}
          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-xs font-semibold text-slate-300 hover:text-white hover:border-orange-500/40 transition-colors"
        >
          Statistiky zápasu
          <ChevronDown
            className={`w-3.5 h-3.5 transition-transform ${open ? 'rotate-180' : ''}`}
          />
        </button>
      </div>

      {open && <GamePanel game={game} onClose={() => setOpen(false)} />}
    </div>
  );
};

/** Čas výhozu v lokálním pásmu (např. 01:00 SEČ) */
const fmtTipoff = (utc: string) => {
  try {
    const d = new Date(utc);
    if (isNaN(d.getTime())) return '–';
    return d.toLocaleTimeString('cs-CZ', { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '–';
  }
};

const fmtTipoffDay = (utc: string) => {
  try {
    const d = new Date(utc);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleDateString('cs-CZ', { day: 'numeric', month: 'numeric' });
  } catch {
    return '';
  }
};

const zoneLabel = () => {
  try {
    const parts = new Intl.DateTimeFormat('cs-CZ', { timeZoneName: 'short' }).formatToParts(
      new Date()
    );
    return parts.find((p) => p.type === 'timeZoneName')?.value ?? '';
  } catch {
    return '';
  }
};

/** Dnešní rozpis zápasů s časy v lokálním pásmu */
function FullSchedule({
  defaultDay = 0,
}: {
  defaultDay?: number;
}) {
  const [innerDay, setInnerDay] = useState(defaultDay);
  return <SchedulePanel day={innerDay} onDayChange={setInnerDay} />;
}

function SchedulePanel({
  day,
  onDayChange,
  compact = false,
}: {
  day: number;
  onDayChange: (day: number) => void;
  compact?: boolean;
}) {
  const [data, setData] = useState<ScheduleResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openGame, setOpenGame] = useState<ScheduleGame | null>(null);
  const zone = zoneLabel();

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    fetch(`${API}/api/news/schedule?day=${day}`)
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || 'Rozpis se nepodařilo načíst.');
        }
        return res.json();
      })
      .then((d: ScheduleResponse) => alive && setData(d))
      .catch((e) =>
        alive &&
        setError(
          e?.message === 'Failed to fetch'
            ? 'Backend neběží – spusť START.bat a zkus to znovu.'
            : e.message || 'Chyba připojení k backendu.'
        )
      )
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [day]);

  const statusBadge = (g: ScheduleGame) => {
    if (g.status === 3) {
      return (
        <span className="px-2 py-0.5 rounded-md text-[10px] font-bold bg-slate-800 text-slate-300">
          Konec
        </span>
      );
    }
    if (g.status === 2) {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-bold bg-red-500/20 text-red-300 border border-red-500/30">
          <Radio className="w-3 h-3 animate-pulse" /> {g.status_text || 'Hraje se'}
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-bold bg-slate-800 text-slate-400">
        <Clock className="w-3 h-3" /> {fmtTipoff(g.tipoff_utc)} {zone}
      </span>
    );
  };

  const teamRow = (t: ScheduleTeam, g: ScheduleGame, isHome: boolean) => {
    const hasScore = g.status > 1;
    const leading =
      hasScore && t.score >= (isHome ? g.away.score : g.home.score) && t.score > 0;
    return (
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className={`w-1 h-6 rounded-full ${isHome ? 'bg-orange-500/70' : 'bg-slate-700'}`}
          />
          <span
            className={`text-xs sm:text-sm font-semibold truncate ${
              leading ? 'text-white' : 'text-slate-300'
            }`}
          >
            {t.name}
          </span>
          <span className="text-[10px] font-mono text-slate-500">{t.abbr}</span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-[10px] text-slate-500 tabular-nums">
            {t.wins}-{t.losses}
          </span>
          {hasScore && (
            <span
              className={`text-base font-black tabular-nums ${
                leading ? 'text-orange-400' : 'text-slate-400'
              }`}
            >
              {t.score}
            </span>
          )}
        </div>
      </div>
    );
  };

  return (
    <section className="rounded-2xl bg-slate-900/90 border border-slate-800 p-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-bold text-white">
          <CalendarClock className="w-4 h-4 text-orange-400" />
          Rozpis zápasů
          <span className="text-[11px] font-normal text-slate-500">
            (časy v tvém pásmu {zone})
          </span>
        </h2>
        <div className="inline-flex items-center gap-1 p-1 rounded-xl bg-slate-950 border border-slate-800">
          {[
            { d: 0, label: 'Dnes' },
            { d: 1, label: 'Zítra' },
            { d: -1, label: 'Včera' },
          ].map((opt) => (
            <button
              key={opt.d}
              onClick={() => onDayChange(opt.d)}
              className={`px-3 py-1 rounded-lg text-xs font-bold transition-colors ${
                day === opt.d
                  ? 'bg-orange-500 text-white'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {loading && (
        <div className="flex items-center justify-center gap-2 py-6 text-xs text-slate-400">
          <Loader2 className="w-4 h-4 animate-spin text-orange-500" />
          Načítám rozpis z NBA API…
        </div>
      )}

      {error && !loading && (
        <div className="flex items-center gap-2 p-3 rounded-lg bg-red-950/40 border border-red-800/70 text-xs text-red-200">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      {!loading && !error && data && (
        <>
          {data.games.length === 0 ? (
            <p className="py-4 text-center text-xs text-slate-500 italic">
              Na tento den nejsou v rozpisu žádné zápasy.
            </p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2.5">
              {data.games.map((g) => (
                <div
                  key={g.game_id}
                  className="rounded-xl bg-slate-950 border border-slate-800 hover:border-orange-500/30 transition-colors p-3 space-y-1.5"
                >
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="text-[10px] font-bold text-slate-500 truncate">
                      {g.label || fmtTipoffDay(g.tipoff_utc)}
                    </span>
                    {statusBadge(g)}
                  </div>
                  {teamRow(g.home, g, true)}
                  {teamRow(g.away, g, false)}
                  <button
                    onClick={() => setOpenGame(g)}
                    className="mt-1 w-full text-[11px] font-semibold py-1 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-white hover:border-orange-500/40 transition-colors"
                  >
                    {g.status > 1 ? 'Statistiky zápasu' : 'Detail zápasu'}
                  </button>
                </div>
              ))}
            </div>
          )}
          <p className="text-[10px] text-slate-600">
            Zdroj: {data.source} · den {data.date} · domácí tým je uvedený první
          </p>
        </>
      )}

      {openGame && (
        <div
          className="fixed inset-0 z-50 flex items-start sm:items-center justify-center p-3 sm:p-6 bg-black/70 backdrop-blur-sm overflow-y-auto"
          onClick={() => setOpenGame(null)}
        >
          <div
            className="w-full max-w-4xl rounded-2xl bg-slate-900 border border-slate-700 shadow-2xl p-4 space-y-3 my-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-sm sm:text-base font-bold text-white">
                  {openGame.home.name} vs {openGame.away.name}
                </h3>
                <p className="text-[11px] text-slate-500">
                  {fmtTipoffDay(openGame.tipoff_utc)} · {fmtTipoff(openGame.tipoff_utc)} {zone} ·{' '}
                  {openGame.label}
                  {openGame.status === 1 && ' · zápas ještě nezačal, statistiky nejsou k dispozici'}
                </p>
              </div>
              <button
                onClick={() => setOpenGame(null)}
                className="shrink-0 px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-400 hover:text-white bg-slate-950 border border-slate-800"
              >
                Zavřít
              </button>
            </div>
            <GamePanel game={openGame} onClose={() => setOpenGame(null)} />
          </div>
        </div>
      )}
    </section>
  );
}

/**
 * Rozpis zápasů nalepený v hlavičce stránky.
 * Ukazuje nejbližší zápasy (dnešní noc + zítřejší), rozbalí se do plného rozpisu.
 */
const StickyScheduleBar: React.FC = () => {
  const [data, setData] = useState<ScheduleResponse | null>(null);
  const [tomorrow, setTomorrow] = useState<ScheduleResponse | null>(null);
  const [yesterday, setYesterday] = useState<ScheduleResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const zone = zoneLabel();

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.all([
      fetch(`${API}/api/news/schedule?day=0`).then((r) => (r.ok ? r.json() : null)),
      fetch(`${API}/api/news/schedule?day=1`).then((r) => (r.ok ? r.json() : null)),
      fetch(`${API}/api/news/schedule?day=-1`).then((r) => (r.ok ? r.json() : null)),
    ])
      .then(
        ([today, next, prev]: [
          ScheduleResponse | null,
          ScheduleResponse | null,
          ScheduleResponse | null
        ]) => {
          if (!alive) return;
          setData(today);
          setTomorrow(next);
          setYesterday(prev);
        }
      )
      .catch(() => alive && setData(null))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  if (loading) {
    return (
      <div className="sticky top-16 z-40 border-b border-slate-800 bg-slate-950/95 backdrop-blur-md">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-2 flex items-center gap-2 text-[11px] text-slate-500">
          <Loader2 className="w-3.5 h-3.5 animate-spin text-orange-500" />
          Načítám rozpis zápasů…
        </div>
      </div>
    );
  }

  const todayGames = data?.games ?? [];
  const tomorrowGames = tomorrow?.games ?? [];
  const yesterdayGames = yesterday?.games ?? [];
  if (todayGames.length === 0 && tomorrowGames.length === 0 && yesterdayGames.length === 0) {
    return null;
  }

  // Pořadí: včerejší výsledky → dnešní živé/plánované → zítřejší zápasy
  const yesterdaySorted = [...yesterdayGames].sort((a, b) =>
    a.tipoff_utc.localeCompare(b.tipoff_utc)
  );
  const todaySorted = [...todayGames].sort((a, b) => {
    const rank = (g: ScheduleGame) => (g.status === 2 ? 0 : g.status === 1 ? 1 : 2);
    const r = rank(a) - rank(b);
    return r !== 0 ? r : a.tipoff_utc.localeCompare(b.tipoff_utc);
  });
  const shown: ScheduleGame[] = [...yesterdaySorted, ...todaySorted, ...tomorrowGames].slice(0, 16);

  const dayOf = (g: ScheduleGame) => {
    if (yesterday?.date && g.tipoff_utc.startsWith(yesterday.date)) return 'yesterday';
    if (tomorrow?.date && g.tipoff_utc.startsWith(tomorrow.date)) return 'tomorrow';
    return 'today';
  };

  const dayDot = (g: ScheduleGame) => {
    const d = dayOf(g);
    if (d === 'yesterday') return 'bg-emerald-400/80';
    if (d === 'tomorrow') return 'bg-sky-400/80';
    return 'bg-orange-400/80';
  };

  const dayTitle = (g: ScheduleGame) => {
    const d = dayOf(g);
    if (d === 'yesterday') return 'Včerejší výsledek';
    if (d === 'tomorrow') return 'Zítřejší zápas';
    return 'Dnešní zápas';
  };

  return (
    <div className="sticky top-16 z-40 border-b border-slate-800 bg-slate-950/95 backdrop-blur-md shadow-lg shadow-black/20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-3 py-1.5">
          <span className="hidden sm:inline-flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-orange-400 shrink-0">
            <CalendarClock className="w-3.5 h-3.5" />
            Program
          </span>
          <span className="hidden lg:flex items-center gap-2 text-[10px] text-slate-500 shrink-0">
            <span className="inline-flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400/80" /> včera
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-orange-400/80" /> dnes
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-sky-400/80" /> zítra
            </span>
          </span>

          {/* Pruh se zápasy */}
          <div className="flex items-center gap-2 overflow-x-auto flex-1 no-scrollbar py-1">
            {shown.map((g) => {
              return (
                <div
                  key={g.game_id}
                  className="flex items-center gap-1.5 shrink-0 px-2 py-1 rounded-lg bg-slate-900 border border-slate-800"
                  title={`${g.home.name} vs ${g.away.name} · ${fmtTipoffDay(g.tipoff_utc)} ${fmtTipoff(g.tipoff_utc)} ${zone}`}
                >
                  <span className="text-[11px] font-bold text-white tabular-nums">
                    {fmtTipoff(g.tipoff_utc)}
                  </span>
                  <span className="text-[10px] text-slate-600">{zone}</span>
                  <span className="text-[11px] font-mono text-slate-300">
                    {g.home.abbr}
                    <span className="text-slate-600">–</span>
                    {g.away.abbr}
                  </span>
                  {g.status > 1 ? (
                    <span className="text-[11px] font-bold text-orange-400 tabular-nums">
                      {g.home.score}:{g.away.score}
                    </span>
                  ) : null}
                  <span className="text-[10px] text-slate-500">
                    {fmtTipoffDay(g.tipoff_utc)}
                  </span>
                  {g.status === 2 && (
                    <Radio className="w-3 h-3 text-red-400 animate-pulse" />
                  )}
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${dayDot(g)}`}
                    title={dayTitle(g)}
                  />
                </div>
              );
            })}
          </div>

          <button
            onClick={() => setExpanded((v) => !v)}
            className="shrink-0 inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-slate-900 border border-slate-800 text-[11px] font-semibold text-slate-300 hover:text-white hover:border-orange-500/40 transition-colors"
          >
            {expanded ? 'Skrýt' : 'Celý rozpis'}
            <ChevronDown
              className={`w-3.5 h-3.5 transition-transform ${expanded ? 'rotate-180' : ''}`}
            />
          </button>
        </div>

        {expanded && (
          <div className="pb-3">
            <FullSchedule defaultDay={0} />
          </div>
        )}
      </div>
    </div>
  );
};

export default function NewsPage() {
  const [data, setData] = useState<NewsGamesResponse | null>(null);
  const [days] = useState(1);
  const [day, setDay] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    fetch(`${API}/api/news/games?days=${days}`)
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || 'Výsledky se nepodařilo načíst.');
        }
        return res.json();
      })
      .then((d: NewsGamesResponse) => alive && setData(d))
      .catch((e) =>
        alive &&
        setError(
          e?.message === 'Failed to fetch'
            ? 'Backend neběží – spusť START.bat a zkus to znovu.'
            : e.message || 'Chyba připojení k backendu.'
        )
      )
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [days]);

  return (
    <div className="space-y-6">
      <StickyScheduleBar />

      <section className="text-center space-y-3 max-w-3xl mx-auto">
        <h1 className="text-3xl sm:text-4xl font-black tracking-tight text-white">
          Novinky &amp; výsledky
        </h1>
        <p className="text-sm sm:text-base text-slate-400">
          V hlavičce je program zápasů (včerejší výsledky, dnešek, zítřek) s časy v tvém pásmu.
          Níž jsou karty zápasů – klikni na <strong>Statistiky zápasu</strong> a otevře se
          boxscore, kde můžeš přepínat mezi oběma týmy.
        </p>
      </section>

      <SchedulePanel day={day} onDayChange={setDay} />

      {loading && (
        <div className="flex flex-col items-center justify-center p-16 space-y-3 bg-slate-900/40 rounded-2xl border border-slate-800">
          <Loader2 className="w-10 h-10 animate-spin text-orange-500" />
          <p className="text-sm font-semibold text-slate-300">
            Stahuji výsledky z NBA API…
          </p>
        </div>
      )}

      {error && !loading && (
        <div className="p-6 rounded-2xl bg-red-950/40 border border-red-800/80 text-center max-w-xl mx-auto space-y-2">
          <AlertCircle className="w-8 h-8 text-red-400 mx-auto" />
          <h3 className="font-bold text-red-200">Výsledky se nepodařilo načíst</h3>
          <p className="text-xs text-red-300">{error}</p>
          <button
            onClick={() => window.location.reload()}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-red-600 hover:bg-red-500 text-white text-xs font-bold"
          >
            Zkusit znovu
          </button>
        </div>
      )}

      {!loading && !error && data && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
            <span className="inline-flex items-center gap-1.5">
              <Trophy className="w-3.5 h-3.5 text-amber-400" />
              Sezóna <strong className="text-white">{data.season}</strong> ·{' '}
              {data.games.length} zápasů
            </span>
            <span>
              Odehrané zápasy ze dne{' '}
              <strong className="text-white">
                {data.last_game_date ? fmtDate(data.last_game_date) : '–'}
              </strong>
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {data.games.map((g) => (
              <GameCard key={g.game_id} game={g} />
            ))}
          </div>

          {data.games.length === 0 && (
            <div className="p-8 text-center text-slate-500 bg-slate-900/40 rounded-2xl border border-slate-800">
              Pro zvolené dny nejsou k dispozici žádné odehrané zápasy.
            </div>
          )}

          <p className="text-center text-[10px] text-slate-600">
            Zdroj: {data.source} · data se mohou zpozdit o několik minut
          </p>
        </>
      )}
    </div>
  );
}
