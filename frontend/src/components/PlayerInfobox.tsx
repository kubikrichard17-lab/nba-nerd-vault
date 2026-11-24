'use client';

import React, { useState, useEffect } from 'react';
import { API } from '@/lib/api';
import { PlayerProfile } from '@/types';
import { Trophy, Award, Globe, GraduationCap, Calendar, ShieldCheck, User } from 'lucide-react';

interface PlayerInfoboxProps {
  player: PlayerProfile;
}

export const PlayerInfobox: React.FC<PlayerInfoboxProps> = ({ player }) => {
  // Vždy oficiální NBA CDN s přesným ID. Když tam fotka není (starší legendy),
  // backend najde ověřenou fotku na Basketball-Reference, jinak se ukážou iniciály.
  const [imgSrc, setImgSrc] = useState(
    `https://cdn.nba.com/headshots/nba/latest/1040x760/${player.id}.png`
  );
  const [imgError, setImgError] = useState(false);
  const [triedFallback, setTriedFallback] = useState(false);

  useEffect(() => {
    setImgSrc(`https://cdn.nba.com/headshots/nba/latest/1040x760/${player.id}.png`);
    setImgError(false);
    setTriedFallback(false);
  }, [player.id]);

  const initials = (player.full_name || '?')
    .split(' ')
    .filter(Boolean)
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();

  const handleImageError = async () => {
    if (triedFallback) {
      setImgError(true);
      return;
    }
    setTriedFallback(true);
    try {
      const res = await fetch(`${API}/api/players/${player.id}/headshot`);
      const data = await res.json();
      if (data?.url && data.source !== 'nba') {
        setImgSrc(data.url);
        return;
      }
    } catch {
      /* iniciály */
    }
    setImgError(true);
  };

  return (
    <aside className="w-full lg:w-80 xl:w-96 shrink-0 bg-slate-900/90 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
      {/* Header Banner */}
      <div className="bg-gradient-to-r from-slate-950 via-slate-900 to-orange-950/40 p-4 border-b border-slate-800 text-center">
        <span className="text-xs font-bold uppercase tracking-wider text-orange-400">
          Oficiální profil NBA
        </span>
        <h2 className="text-2xl font-black text-white mt-0.5 tracking-tight">
          {player.full_name}
        </h2>
        <div className="flex items-center justify-center gap-2 mt-1.5">
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-orange-500/20 text-orange-400 border border-orange-500/30">
            {player.position || 'G/F'}
          </span>
          {player.is_active && (
            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
              Aktivní v NBA
            </span>
          )}
        </div>
      </div>

      {/* Headshot Card */}
      <div className="relative p-4 bg-gradient-to-b from-slate-900 to-slate-950 flex flex-col items-center justify-center border-b border-slate-800">
        <div className="relative w-48 h-48 sm:w-56 sm:h-56 rounded-2xl overflow-hidden bg-slate-800/80 border border-slate-700/60 shadow-inner flex items-center justify-center">
          {!imgError ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={imgSrc}
              alt={player.full_name}
              onError={handleImageError}
              referrerPolicy="no-referrer"
              className="w-full h-full object-cover object-top hover:scale-105 transition-transform duration-300"
            />
          ) : (
            <div className="flex flex-col items-center justify-center text-slate-500">
              <span className="text-5xl font-black text-slate-500 tracking-tight">{initials}</span>
              <span className="text-xs font-medium mt-2">Foto nedostupné</span>
            </div>
          )}
        </div>
        <div className="text-[11px] text-slate-400 mt-2 text-center">
          NBA Headshot ID: <span className="font-mono text-slate-300">#{player.id}</span>
        </div>
      </div>

      {/* Wikipedia-style Key Specs Table */}
      <div className="p-4 space-y-3">
        <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 border-b border-slate-800 pb-1 flex items-center gap-1.5">
          <ShieldCheck className="w-3.5 h-3.5 text-orange-400" />
          Základní fyzické a herní parametry
        </h3>

        <div className="text-xs divide-y divide-slate-800/60 font-medium">
          {/* Výška */}
          <div className="py-2 flex justify-between items-center">
            <span className="text-slate-400">Výška:</span>
            <span className="text-slate-100 font-semibold">
              {player.height_cm ? `${player.height_cm} cm` : '-'}{' '}
              <span className="text-slate-400 text-[11px]">
                ({player.height_ft || '-'})
              </span>
            </span>
          </div>

          {/* Váha */}
          <div className="py-2 flex justify-between items-center">
            <span className="text-slate-400">Váha:</span>
            <span className="text-slate-100 font-semibold">
              {player.weight_kg ? `${player.weight_kg} kg` : '-'}{' '}
              <span className="text-slate-400 text-[11px]">
                ({player.weight_lbs ? `${player.weight_lbs} lbs` : '-'})
              </span>
            </span>
          </div>

          {/* Pozice */}
          <div className="py-2 flex justify-between items-center">
            <span className="text-slate-400">Pozice:</span>
            <span className="text-orange-400 font-bold">
              {player.position || 'Neuvedeno'}
            </span>
          </div>

          {/* Draft */}
          <div className="py-2 flex justify-between items-start">
            <span className="text-slate-400 flex items-center gap-1">
              <Calendar className="w-3 h-3 text-slate-500" />
              Draft:
            </span>
            <span className="text-right text-slate-200">
              {player.draft_year && player.draft_year !== 'Undrafted' ? (
                <>
                  <span className="font-semibold">{player.draft_year}</span> (Kolo: {player.draft_round}, #{player.draft_number})
                  {player.draft_team && (
                    <div className="text-[11px] text-slate-400">{player.draft_team}</div>
                  )}
                </>
              ) : (
                <span className="text-slate-400">Nedraftován (Undrafted)</span>
              )}
            </span>
          </div>

          {/* Univerzita */}
          <div className="py-2 flex justify-between items-start">
            <span className="text-slate-400 flex items-center gap-1">
              <GraduationCap className="w-3 h-3 text-slate-500" />
              Univerzita / Škola:
            </span>
            <span className="text-right text-slate-200 max-w-[160px] truncate">
              {player.college || '-'}
            </span>
          </div>

          {/* Země původu */}
          <div className="py-2 flex justify-between items-center">
            <span className="text-slate-400 flex items-center gap-1">
              <Globe className="w-3 h-3 text-slate-500" />
              Země původu:
            </span>
            <span className="text-slate-200">{player.country || 'USA'}</span>
          </div>
        </div>

        {/* Trophies & Awards Showcase */}
        <div className="pt-2">
          <h3 className="text-xs font-bold uppercase tracking-wider text-amber-400 border-b border-slate-800 pb-1 flex items-center gap-1.5">
            <Trophy className="w-3.5 h-3.5 text-amber-400" />
            Získané trofeje a ocenění NBA
          </h3>

          <div className="mt-2.5 space-y-1.5">
            {player.awards && player.awards.length > 0 ? (
              player.awards.map((award, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between p-2 rounded-lg bg-slate-950 border border-slate-800/80 hover:border-amber-500/30 transition-all text-xs"
                >
                  <div className="flex items-center space-x-2">
                    <Award className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                    <span className="text-slate-200 font-medium">
                      {award.description_cs || award.description}
                    </span>
                  </div>
                  <span className="px-2 py-0.5 rounded-full font-bold bg-amber-500/10 text-amber-400 border border-amber-500/30 text-[11px] shrink-0">
                    {award.count}x
                  </span>
                </div>
              ))
            ) : (
              <div className="text-xs text-slate-500 italic p-2 text-center bg-slate-950/50 rounded-lg">
                Žádné individuální trofeje nejsou v záznamu evidovány.
              </div>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
};
