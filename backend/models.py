from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Text, ForeignKey, DateTime
)
from sqlalchemy.orm import relationship
from database import Base


class Player(Base):
    __tablename__ = "players"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(100), index=True, nullable=False)
    first_name = Column(String(50), nullable=True)
    last_name = Column(String(50), nullable=True)
    is_active = Column(Boolean, default=False)
    
    # Headshot & Media
    headshot_url = Column(String(255), nullable=True)
    
    # Physical specs
    height_cm = Column(Float, nullable=True)
    height_ft = Column(String(20), nullable=True)
    weight_kg = Column(Float, nullable=True)
    weight_lbs = Column(Float, nullable=True)
    position = Column(String(30), nullable=True)
    
    # Draft & Origin
    draft_year = Column(String(10), nullable=True)
    draft_round = Column(String(10), nullable=True)
    draft_number = Column(String(10), nullable=True)
    draft_team = Column(String(100), nullable=True)
    college = Column(String(100), nullable=True)
    country = Column(String(50), nullable=True)
    
    # Wikipedia summary & AI Scout Report (in Czech)
    bio_summary = Column(Text, nullable=True)
    scouting_report = Column(Text, nullable=True)
    playstyle_tags = Column(Text, nullable=True)  # JSON-encoded array of Czech tags

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    stats = relationship("PlayerSeasonStat", back_populates="player", cascade="all, delete-orphan")
    awards = relationship("PlayerAward", back_populates="player", cascade="all, delete-orphan")


class PlayerSeasonStat(Base):
    __tablename__ = "player_season_stats"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    player_id = Column(Integer, ForeignKey("players.id"), index=True)
    season_id = Column(String(20), index=True, nullable=False)  # e.g. "1997-98"
    team_abbreviation = Column(String(10), nullable=True)
    player_age = Column(Integer, nullable=True)
    
    # Games & Minutes
    gp = Column(Integer, default=0)
    gs = Column(Integer, default=0)
    min_total = Column(Float, default=0.0)
    min_per_game = Column(Float, default=0.0)
    
    # Per game stats
    pts = Column(Float, default=0.0)
    reb = Column(Float, default=0.0)
    ast = Column(Float, default=0.0)
    stl = Column(Float, default=0.0)
    blk = Column(Float, default=0.0)
    tov = Column(Float, default=0.0)
    pf = Column(Float, default=0.0)
    
    # Shooting percentages & totals
    fgm = Column(Float, default=0.0)
    fga = Column(Float, default=0.0)
    fg_pct = Column(Float, default=0.0)
    fg3m = Column(Float, default=0.0)
    fg3a = Column(Float, default=0.0)
    fg3_pct = Column(Float, default=0.0)
    ftm = Column(Float, default=0.0)
    fta = Column(Float, default=0.0)
    ft_pct = Column(Float, default=0.0)

    # Per 100 Possessions estimated stats
    poss100_pts = Column(Float, default=0.0)
    poss100_reb = Column(Float, default=0.0)
    poss100_ast = Column(Float, default=0.0)
    poss100_stl = Column(Float, default=0.0)
    poss100_blk = Column(Float, default=0.0)
    poss100_tov = Column(Float, default=0.0)

    player = relationship("Player", back_populates="stats")


class PlayerAward(Base):
    __tablename__ = "player_awards"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    player_id = Column(Integer, ForeignKey("players.id"), index=True)
    description = Column(String(150), nullable=False)
    description_cs = Column(String(150), nullable=True)
    season = Column(String(20), nullable=True)
    award_type = Column(String(50), nullable=True)
    count = Column(Integer, default=1)

    player = relationship("Player", back_populates="awards")


class ComparisonCache(Base):
    __tablename__ = "comparison_cache"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    cache_key = Column(String(100), unique=True, index=True)
    match_pct = Column(Float, default=0.0)
    physical_pct = Column(Float, default=0.0)
    statistical_pct = Column(Float, default=0.0)
    stylistic_pct = Column(Float, default=0.0)
    ai_verdict = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ClosestCache(Base):
    """
    Uložený výsledek „Nejbližší hráč" pro daného hráče.

    Klíč obsahuje verzi výpočtu, takže po změně vah nebo logiky se
    stará cache automaticky přestane používat a nic se nemusí mazat.
    """

    __tablename__ = "closest_cache"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    cache_key = Column(String(120), unique=True, index=True)
    player_id = Column(Integer, index=True, nullable=False)
    closest_id = Column(Integer, nullable=True)
    payload = Column(Text, nullable=False)   # celá odpověď jako JSON
    created_at = Column(DateTime, default=datetime.utcnow)
