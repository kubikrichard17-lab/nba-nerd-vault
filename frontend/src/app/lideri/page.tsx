'use client';

import React, { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { AlertCircle, Crown, Loader2, Trophy, Users, Globe2, CalendarRange } from 'lucide-react';
import type { LeaderRow, LeadersMeta, LeadersResponse } from '@/types/news';
import { API } from '@/lib/api';


const fmtValue = (row: LeaderRow, stat: string) => {
  if (stat.endsWith('_PCT')) return `${Math.round(row.value * 1000) / 10}%`;
  return row.per_game ? row.value.toFixed(1) : row.value.toLocaleString('cs-CZ');
};

const fmtTotal = (row: LeaderRow, stat: string) => {
  if (stat.endsWith('_PCT')) return `${row.gp} Z`;
  return row.per_game ? row.total.toLocaleString('cs-CZ') : `${row.gp} Z`;
};

const MEDALS = ['text-amber-400', 'text-slate-300', 'text-orange-400'];

export default function LeadersPage() {
  const [meta, setMeta] = useState<LeadersMeta | null>(null);
  const [mode, setMode] = useState<'alltime' | 'season' | 'team'>('season');
  const [stat, setStat] = useState('PTS');
  const [perGame, setPerGame] = useState(true);
  const [team, setTeam] = useState('BOS');
  const [season, setSeason] = useState<string>('');
  const [limit, setLimit] = useState(15);

  const [data, setData] = useState<LeadersResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Načtení možností (statistiky, týmy)
  useEffect(() => {
    fetch(`${API}/api/leaders/meta`)
      .then((r) => r.json())
      .then((m: LeadersMeta) => {
        setMeta(m);
        setSeason(m.current_season);
      })
      .catch(() => setMeta(null));
  }, []);

  const statDef = useMemo(
    () => meta?.stats.find((s) => s.key === stat),
    [meta, stat]
  );

  // Procenta nemají smysl "na zápas"
  useEffect(() => {
    if (statDef && !statDef.per_game_available) setPerGame(false);
  }, [statDef]);

  const fetchLeaders = () => {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({
      mode,
      stat,
      per_game: String(perGame),
      limit: String(limit),
    });
    if (mode === 'team') params.set('team', team);
    if (mode === 'season' && season) params.set('season', season);

    fetch(`${API}/api/leaders?${params.toString()}`)
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || 'Žebříček se nepodařilo načíst.');
        }
        return res.json();
      })
      .then((d: LeadersResponse) => setData(d))
      .catch((e) => {
        setData(null);
        setError(e.message || 'Chyba připojení k backendu.');
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchLeaders();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, stat, perGame, team, season, limit]);

  const modeBtn = (key: 'alltime' | 'season' | 'team', label: string, Icon: any) => {
    const active = mode === key;
    return (
      <button
        key={key}
        onClick={() => setMode(key)}
        className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-bold transition-all ${
          active
            ? 'bg-orange-500 text-white shadow-md shadow-orange-500/25'
            : 'bg-slate-900 text-slate-400 border border-slate-800 hover:text-white'
        }`}
      >
        <Icon className="w-4 h-4" />
        {label}
      </button>
    );
  };

  return (
    <div className="space-y-6">
      <section className="text-center space-y-3 max-w-3xl mx-auto">
        <h1 className="text-3xl sm:text-4xl font-black tracking-tight text-white">
          Lídři statistik
        </h1>
        <p className="text-sm sm:text-base text-slate-400">
          All-Time rekordy, lídři aktuální sezóny i historické žebříčky jednotlivých franšíz.
          Přepni si statistiku i to, jestli chceš průměr na zápas, nebo celkový součet.
        </p>
      </section>

      {/* Režimy */}
      <div className="flex flex-wrap items-center justify-center gap-2">
        {modeBtn('alltime', 'All-Time', Globe2)}
        {modeBtn('season', 'Sezóna', CalendarRange)}
        {modeBtn('team', 'Tým / franšíza', Users)}
      </div>

      {/* Filtry */}
      <div className="rounded-2xl bg-slate-900/90 border border-slate-800 p-4 space-y-4">
        <div className="flex flex-wrap gap-1.5">
          {(meta?.stats ?? []).map((s) => (
            <button
              key={s.key}
              onClick={() => setStat(s.key)}
              className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-colors border ${
                stat === s.key
                  ? 'bg-orange-500/20 text-orange-300 border-orange-500/40'
                  : 'bg-slate-950 text-slate-400 border-slate-800 hover:text-white'
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Na zápas / celkem */}
          <div className="inline-flex items-center gap-1 p-1 rounded-xl bg-slate-950 border border-slate-800">
            <button
              disabled={statDef ? !statDef.per_game_available : false}
              onClick={() => setPerGame(true)}
              className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-colors ${
                perGame
                  ? 'bg-orange-500 text-white'
                  : 'text-slate-400 hover:text-white disabled:opacity-40 disabled:hover:text-slate-400'
              }`}
            >
              Průměr na zápas
            </button>
            <button
              onClick={() => setPerGame(false)}
              className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-colors ${
                !perGame
                  ? 'bg-orange-500 text-white'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              Celkem
            </button>
          </div>

          {/* Tým */}
          {mode === 'team' && (
            <select
              value={team}
              onChange={(e) => setTeam(e.target.value)}
              className="px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-xs font-semibold text-slate-200 outline-none focus:border-orange-500/60"
            >
              {(meta?.teams ?? []).map((t) => (
                <option key={t.abbr} value={t.abbr}>
                  {t.name} ({t.abbr})
                </option>
              ))}
            </select>
          )}

          {/* Sezóna */}
          {mode === 'season' && meta && (
            <select
              value={season}
              onChange={(e) => setSeason(e.target.value)}
              className="px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-xs font-semibold text-slate-200 outline-none focus:border-orange-500/60"
            >
              {[meta.current_season, ...meta.seasons.filter((s) => s !== meta.current_season)].map(
                (s) => (
                  <option key={s} value={s}>
                    Sezóna {s}
                  </option>
                )
              )}
            </select>
          )}

          {/* Počet */}
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-xs font-semibold text-slate-200 outline-none focus:border-orange-500/60"
          >
            {[10, 15, 20, 30, 50].map((n) => (
              <option key={n} value={n}>
                Top {n}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Výsledky */}
      {loading && (
        <div className="flex flex-col items-center justify-center p-16 space-y-3 bg-slate-900/40 rounded-2xl border border-slate-800">
          <Loader2 className="w-10 h-10 animate-spin text-orange-500" />
          <p className="text-sm font-semibold text-slate-300">Počítám žebříček…</p>
          <p className="text-xs text-slate-500">
            All-Time žebříčky se poprvé sestavují ze všech sezón, může to chvíli trvat.
          </p>
        </div>
      )}

      {error && !loading && (
        <div className="p-6 rounded-2xl bg-red-950/40 border border-red-800/80 text-center max-w-xl mx-auto space-y-2">
          <AlertCircle className="w-8 h-8 text-red-400 mx-auto" />
          <h3 className="font-bold text-red-200">Žebříček se nepodařilo načíst</h3>
          <p className="text-xs text-red-300">{error}</p>
          <button
            onClick={fetchLeaders}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-red-600 hover:bg-red-500 text-white text-xs font-bold"
          >
            Zkusit znovu
          </button>
        </div>
      )}

      {!loading && !error && data && (
        <div className="rounded-2xl bg-slate-900/90 border border-slate-800 overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 border-b border-slate-800 bg-slate-950/60">
            <h2 className="flex items-center gap-2 text-sm font-bold text-white">
              <Trophy className="w-4 h-4 text-amber-400" />
              {data.title}
            </h2>
            <span className="text-[11px] font-semibold text-slate-400">
              {data.per_game ? 'Průměr na zápas' : 'Celkový součet'} · Top {data.rows.length}
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-xs sm:text-sm">
              <thead className="bg-slate-950/70 text-[11px] uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="px-3 py-2 text-left">#</th>
                  <th className="px-3 py-2 text-left">Hráč</th>
                  <th className="px-3 py-2 text-left">Tým</th>
                  <th className="px-3 py-2 text-right">{data.stat_label}</th>
                  <th className="px-3 py-2 text-right">
                    {data.stat.endsWith('_PCT') ? 'Zápasy' : data.per_game ? 'Celkem' : 'Zápasy'}
                  </th>
                  <th className="px-3 py-2 text-right">Období</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-900">
                {data.rows.map((row) => (
                  <tr key={`${row.player_id}-${row.rank}`} className="hover:bg-slate-950/60">
                    <td className="px-3 py-2 font-black tabular-nums">
                      <span className={row.rank <= 3 ? MEDALS[row.rank - 1] : 'text-slate-500'}>
                        {row.rank === 1 ? <Crown className="w-4 h-4 inline" /> : row.rank}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <Link
                        href={`/?player=${row.player_id}`}
                        className="flex items-center gap-2 font-semibold text-white hover:text-orange-400 transition-colors"
                      >
                        <img
                          src={`https://cdn.nba.com/headshots/nba/latest/260x190/${row.player_id}.png`}
                          alt={row.name}
                          className="w-7 h-7 rounded-full object-cover bg-slate-800 shrink-0"
                          onError={(e) => {
                            (e.target as HTMLImageElement).style.visibility = 'hidden';
                          }}
                        />
                        {row.name}
                      </Link>
                    </td>
                    <td className="px-3 py-2 text-slate-400 font-mono text-[11px]">
                      {row.team || '–'}
                    </td>
                    <td className="px-3 py-2 text-right font-black text-orange-400 tabular-nums">
                      {fmtValue(row, data.stat)}
                    </td>
                    <td className="px-3 py-2 text-right text-slate-400 tabular-nums">
                      {fmtTotal(row, data.stat)}
                    </td>
                    <td className="px-3 py-2 text-right text-slate-500 text-[11px]">
                      {row.season_span || row.season || '–'}
                    </td>
                  </tr>
                ))}
                {data.rows.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-3 py-8 text-center text-slate-500 italic">
                      Pro tuto kombinaci nejsou data k dispozici.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {data.note && (
            <p className="px-4 py-2.5 text-[11px] text-amber-300/80 border-t border-slate-800 bg-amber-950/10">
              {data.note}
            </p>
          )}
          <p className="px-4 py-2 text-[10px] text-slate-600 border-t border-slate-800">
            Zdroj: {data.source}
          </p>
        </div>
      )}
    </div>
  );
}
