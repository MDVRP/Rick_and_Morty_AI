from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple
import difflib
import uuid
import os

from src.config import (
    DB_PATH,
    TABLE_CHARACTERS,
    TABLE_EPISODES,
    TABLE_LOCATIONS,
    SCHEMA_JSON_PATH,
    TABLE_NOTES,
)


class Store:
    """
    SQLite-backed store for locations, characters, episodes, and query metadata.
    - Lists are stored as JSON (TEXT) columns.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or DB_PATH
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        # Ensure the directory for the database exists
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _ensure_schema(self) -> None:
        with closing(self._connect()) as conn, conn:
            # Episodes table
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE_EPISODES} (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    code TEXT
                );
                """
            )
            # Notes table (simple): notes text and embedding (JSON list of numbers stored as TEXT)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS Notes (
                    notes TEXT,
                    embedding TEXT
                );
                """
            )
            # Locations table
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE_LOCATIONS} (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    type TEXT,
                    dimension TEXT,
                    residents TEXT
                );
                """
            )
            # Characters table (no location_id stored)
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE_CHARACTERS} (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    status TEXT,
                    species TEXT,
                    type TEXT,
                    gender TEXT,
                    image TEXT,
                    episodes TEXT,
                    location_id TEXT 
                );
                """
            )
            
        # After ensuring schema, write current schema JSON
        self.dump_all_table_schemas()

    @staticmethod
    def _json_dumps(value: Any) -> str:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _json_loads(value: Optional[str]) -> Any:
        if not value:
            return None
        return json.loads(value)

    def _upsert_episode(self, conn: sqlite3.Connection, ep: Dict[str, Any]) -> None:
        ep_id = str(ep.get("id")) if ep.get("id") is not None else None
        if not ep_id:
            return
        name = ep.get("name")
        code = ep.get("episode")
        conn.execute(
            f"""
            INSERT INTO {TABLE_EPISODES} (id, name, code)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                code=excluded.code;
            """,
            (ep_id, name, code),
        )

    def _merge_unique(self, existing: Iterable[str], new_items: Iterable[str]) -> List[str]:
        seen = set(existing or [])
        merged: List[str] = list(existing or [])
        for item in new_items or []:
            if item not in seen:
                seen.add(item)
                merged.append(item)
        return merged

    def _upsert_character(self, conn: sqlite3.Connection, ch: Dict[str, Any], location_id: Optional[str] = None) -> None:
        ch_id = str(ch.get("id")) if ch.get("id") is not None else None
        if not ch_id:
            return
        # Insert or update scalar fields
        name = ch.get("name")
        status = ch.get("status")
        species = ch.get("species")
        ch_type = ch.get("type")
        gender = ch.get("gender")
        image = ch.get("image")
        location_id = location_id or None
        # Episodes on character
        episodes = ch.get("episode") or []
        episode_ids: List[str] = []
        for ep in episodes:
            self._upsert_episode(conn, ep)
            ep_id = ep.get("id")
            if ep_id is not None:
                episode_ids.append(str(ep_id))
        # Deduplicate incoming episode ids; do not overwrite existing non-null episodes later
        if episode_ids:
            # Preserve original ordering while de-duping
            seen_local = set()
            episode_ids = [eid for eid in episode_ids if not (eid in seen_local or seen_local.add(eid))]
        episodes_json_str = self._json_dumps(episode_ids)
        conn.execute(
            f"""
            INSERT INTO {TABLE_CHARACTERS}
                (id, name, status, species, type, gender, image, episodes, location_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                status=excluded.status,
                species=excluded.species,
                type=excluded.type,
                gender=excluded.gender,
                image=excluded.image,
                episodes=COALESCE({TABLE_CHARACTERS}.episodes, excluded.episodes),
                location_id=excluded.location_id
            ;
            """,
            (
                ch_id,
                name,
                status,
                species,
                ch_type,
                gender,
                image,
                episodes_json_str,  # episodes value for INSERT
                location_id,
            ),
        )

    def _upsert_location(self, conn: sqlite3.Connection, loc: Dict[str, Any]) -> None:
        loc_id = str(loc.get("id")) if loc.get("id") is not None else None
        if not loc_id:
            return
        name = loc.get("name")
        loc_type = loc.get("type")
        dimension = loc.get("dimension")

        # Build residents list with minimal information (id + name)
        residents = loc.get("residents") or []
        residents_compact = []
        for r in residents:
            r_id = r.get("id")
            if r_id is None:
                continue
            residents_compact.append({"id": str(r_id), "name": r.get("name")})

        conn.execute(
            f"""
            INSERT INTO {TABLE_LOCATIONS} (id, name, type, dimension, residents)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                type=excluded.type,
                dimension=excluded.dimension,
                residents=excluded.residents
            ;
            """,
            (
                loc_id,
                name,
                loc_type,
                dimension,
                self._json_dumps(residents_compact),
            ),
        )

    def ingest_locations(self, locations: List[Dict[str, Any]]) -> None:
        """
        Ingest complete locations data:
        - Upsert each episode encountered.
        - Upsert each resident character and merge their episode ids list.
        - Upsert each location and store residents list (id + name).
        """
        with closing(self._connect()) as conn, conn:
            for loc in locations:
                # Upsert location first
                self._upsert_location(conn, loc)
                # Upsert characters (and their episodes)
                for resident in loc.get("residents") or []:
                    self._upsert_character(conn, resident, location_id=loc.get("id"))

    def ingest_from_reader(self, reader: Any) -> None:
        """
        Convenience: fetch all locations via reader and ingest.
        Reader must provide fetch_all_locations() -> List[Dict].
        """
        locations = reader.fetch_all_locations()
        self.ingest_locations(locations)
        # After ingestion, print total counts of locations and characters stored
        with closing(self._connect()) as conn:
            cur = conn.execute(f"SELECT COUNT(*) FROM {TABLE_LOCATIONS}")
            total_locations = cur.fetchone()[0] if cur else 0
            cur = conn.execute(f"SELECT COUNT(*) FROM {TABLE_CHARACTERS}")
            total_characters = cur.fetchone()[0] if cur else 0
        print(f"Total locations ingested: {total_locations}")
        print(f"Total characters ingested: {total_characters}")

    # Schema utilities
    def get_table_schema(self, table: str) -> List[Dict[str, Any]]:
        """
        Return schema info for a table using PRAGMA table_info.
        """
        with closing(self._connect()) as conn:
            cur = conn.execute(f"PRAGMA table_info({table});")
            rows = cur.fetchall()
        schema: List[Dict[str, Any]] = []
        for cid, name, col_type, notnull, dflt_value, pk in rows:
            schema.append(
                {
                    "name": name,
                    "type": col_type,
                    "notnull": bool(notnull),
                    "default": dflt_value,
                    "primary_key": bool(pk),
                }
            )
        return schema

    def dump_all_table_schemas(self, output_path: Optional[str] = None) -> str:
        """
        Dump schemas for all known tables to a JSON file.
        Returns the path written.
        """
        path = output_path or SCHEMA_JSON_PATH
        tables = [
            TABLE_EPISODES,
            TABLE_CHARACTERS,
            TABLE_LOCATIONS,
            TABLE_NOTES,
        ]
        all_schemas: Dict[str, Any] = {}
        for t in tables:
            all_schemas[t] = self.get_table_schema(t)
        # Ensure directory exists
        import os

        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(all_schemas, f, ensure_ascii=False, indent=2)
        return path

    # Name to notes resolver
    def add_note_by_name(
        self,
        name: str,
        note: str,
        similarity_threshold: float = 0.6,
    ) -> Dict[str, Any]:
        """
        Add a note for a character resolved by name. Resolution strategy:
        1) Exact (case-insensitive) match on characters.name -> insert note (source='exact').
        2) Else, pick highest similarity via difflib; if >= threshold -> insert note (source='approx').
        3) Else, create a placeholder character and insert note (source='new').
        The original provided name is stored in character_notes.original_name.
        Returns metadata: {character_id, matched_name, match_type, note_id}.
        """
        provided_name = (name or "").strip()
        if not provided_name:
            raise ValueError("name must be a non-empty string")
        with closing(self._connect()) as conn, conn:
            # fetch all character names
            cur = conn.execute(f"SELECT id, name FROM {TABLE_CHARACTERS};")
            rows = cur.fetchall()
            # try exact case-insensitive
            lowered = provided_name.lower()
            exact_id: Optional[str] = None
            exact_name: Optional[str] = None
            for cid, cname in rows:
                if (cname or "").lower() == lowered:
                    exact_id = str(cid)
                    exact_name = cname
                    break
            if exact_id:
                note_id = self._insert_note(
                    conn,
                    character_id=exact_id,
                    note=note,
                    source="exact",
                    original_name=provided_name,
                )
                return {
                    "character_id": exact_id,
                    "matched_name": exact_name,
                    "match_type": "exact",
                    "note_id": note_id,
                }
            # fuzzy match using difflib
            best_id: Optional[str] = None
            best_name: Optional[str] = None
            best_ratio: float = -1.0
            for cid, cname in rows:
                if not cname:
                    continue
                r = difflib.SequenceMatcher(None, lowered, cname.lower()).ratio()
                if r > best_ratio:
                    best_ratio = r
                    best_id = str(cid)
                    best_name = cname
            if best_id is not None and best_ratio >= similarity_threshold:
                note_id = self._insert_note(
                    conn,
                    character_id=best_id,
                    note=note,
                    source="approx",
                    original_name=provided_name,
                )
                return {
                    "character_id": best_id,
                    "matched_name": best_name,
                    "match_type": "approx",
                    "note_id": note_id,
                    "similarity": best_ratio,
                }
            # fallback: create placeholder character
            placeholder_id = f"local_{uuid.uuid4().hex}"
            conn.execute(
                f"""
                INSERT INTO {TABLE_CHARACTERS} (id, name, episodes)
                VALUES (?, ?, ?)
                """,
                (placeholder_id, provided_name, self._json_dumps([])),
            )
            note_id = self._insert_note(
                conn,
                character_id=placeholder_id,
                note=note,
                source="new",
                original_name=provided_name,
            )
            return {
                "character_id": placeholder_id,
                "matched_name": provided_name,
                "match_type": "new",
                "note_id": note_id,
            }

    def _insert_note(
        self,
        conn: sqlite3.Connection,
        character_id: str,
        note: str,
        source: str,
        original_name: Optional[str],
        embedding: Optional[List[float]] = None,
    ) -> int:
        created_at = datetime.utcnow().isoformat() + "Z"
        embedding_json = self._json_dumps(embedding) if embedding is not None else None
        # Resolve character_name and location_name
        char_name: Optional[str] = None
        location_name: Optional[str] = None
        ccur = conn.execute(
            f"SELECT c.name, l.name FROM {TABLE_CHARACTERS} c LEFT JOIN {TABLE_LOCATIONS} l ON l.id = c.location_id WHERE c.id=?",
            (character_id,),
        )
        crow = ccur.fetchone()
        if crow and crow[0]:
            char_name = crow[0]
            location_name = crow[1]
        else:
            # Fallback: if character_id is actually a name, try to resolve by name
            ccur = conn.execute(
                f"SELECT c.id, c.name, l.name FROM {TABLE_CHARACTERS} c LEFT JOIN {TABLE_LOCATIONS} l ON l.id = c.location_id WHERE lower(c.name)=lower(?) LIMIT 1",
                (character_id,),
            )
            crow = ccur.fetchone()
            if crow:
                char_name = crow[1]
                location_name = crow[2]
            else:
                # Last resort: use provided original_name as the character_name
                char_name = original_name or character_id

        cur = conn.execute(
            f"""
            SELECT id, notes FROM {TABLE_NOTES}
            WHERE lower(character_name)=lower(?) AND (lower(location_name)=lower(?) OR (location_name IS NULL AND ? IS NULL))
            """,
            (char_name, location_name, location_name),
        )
        row = cur.fetchone()
        if row:
            note_id, notes_json = row
            try:
                notes_list = json.loads(notes_json) if notes_json else []
                if not isinstance(notes_list, list):
                    notes_list = []
            except Exception:
                notes_list = []
            notes_list.append(note)
            conn.execute(
                f"""
                UPDATE {TABLE_NOTES}
                SET notes=?, embedding=?, source=?, created_at=?, location_name=COALESCE(?, location_name)
                WHERE id=?
                """,
                (
                    self._json_dumps(notes_list),
                    embedding_json,
                    source,
                    created_at,
                    location_name,
                    int(note_id),
                ),
            )
            return int(note_id)
        else:
            # Insert new row with initial notes list
            notes_list = [note]
            cur = conn.execute(
                f"""
                INSERT INTO {TABLE_NOTES} (character_name, location_name, notes, embedding, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    char_name,
                    location_name,
                    self._json_dumps(notes_list),
                    embedding_json,
                    source,
                    created_at,
                ),
            )
            return int(cur.lastrowid)


