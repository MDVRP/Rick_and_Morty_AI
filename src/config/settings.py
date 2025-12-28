import os

GRAPHQL_URL = "https://rickandmortyapi.com/graphql"

REQUEST_HEADERS = {
    "Content-Type": "application/json",
}

REQUEST_TIMEOUT_SECONDS = 20

MAX_RETRIES = 3

# Absolute path to the stored GraphQL query file
QUERY_FILE_PATH = "/Users/aditisharma/Personal/ADITI/Project/Rick_and_Morty_AI/options/ingestion_query"

# SQLite database file path
DB_PATH = "/Users/aditisharma/Personal/ADITI/Project/Rick_and_Morty_AI/data/rick_and_morty.db"

# Logical table names
TABLE_LOCATIONS = "locations"
TABLE_CHARACTERS = "characters"
TABLE_EPISODES = "episodes"
TABLE_QUERIES = "queries"
TABLE_NOTES = "notes"

# Schema JSON output path
SCHEMA_JSON_PATH = "/Users/aditisharma/Personal/ADITI/Project/Rick_and_Morty_AI/schema/tables_schema.json"

# Ollama (ChatOllama) configuration
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3.1"
OLLAMA_NUM_PREDICT = 2000
OLLAMA_TEMPERATURE = 0.6
OLLAMA_EMBED_MODEL = "nomic-embed-text"

# LLM system messages
SQL_SYSTEM_MESSAGE = (
    """You are an SQLite assistant. 
    Analyse the sentiment of the users query wether they want to know somethings or they want to share some new information,  
    Then "think" step-by-step or reason about the schema and the user's intent and then generate a valid SQLite query, .
    Only generate the query dont provide , any comment , notes or explanation 
    Based on the sentiment of the user's query, you may need to generate a query to perform the task the user wants to perform.
    either the user is sharing an information to add the data to the notes as note.
    or the user is querying to know details about something based on the data, you may need to generate a query to know the data from the database.
    or the user's query is to delete the data from the database, you may need to generate a query to delete the data from the database, preferably delete the data from the notes table as well.
    At all times user will only provide you with the name of the charachter or name of the location or name of the episode or notes for you to use , and no other column information will be provided (Dont change anything in the name user has provided) .
    Always perform an inner join with the characters and locations table with common column in the table schema to derive as much context as possible if you are not updating anything, 
    Refer to the columns after the join along with their table names even in where clause , there could be duplicate columns after the join .for eg : character.name and location.name.
    Strictly stick to the provided database schema to generate the query. 
    Dont confuse the table alias of the two tables.
    Especially when deriving information for a character , make sure to join to location table for its location reference and vice versa.
    Always use SQLite-specific syntax, such as json_array_length(column_name) instead of JSON_LENGTH(column_name).
    avoid using specifc column names for example Select name instead use select * 
    Treat JSON columns as opaque text and do not attempt to parse them in SQL. 
    Return only the SQL.
    Follow some complex examples for reference :
    query_1 : Explain me about Zigerion's Base in a conversation between the charachters Rick Sanchez and Beebo. 
    SQL_1 : WITH target_loc AS (
  SELECT id, name, type, dimension, residents
  FROM locations
  WHERE lower(name) = 'zigerion''s base'
  LIMIT 1
),
-- the two speakers we care about (exists even if not residents of the location)
two_chars AS (
  SELECT c.id, c.name, c.status, c.species, c.type, c.gender, c.image, c.episodes
  FROM characters c
  WHERE lower(c.name) IN ('rick sanchez','beebo')
),
-- explode location residents to match by character id (requires SQLite JSON1)
loc_residents AS (
  SELECT json_extract(r.value,'$.id') AS resident_id
  FROM target_loc tl, json_each(tl.residents) AS r
),
two_chars_flagged AS (
  SELECT
    tc.*,
    EXISTS (SELECT 1 FROM loc_residents lr WHERE lr.resident_id = tc.id) AS is_resident_of_location
  FROM two_chars tc
),
-- gather some episode codes for each character (requires JSON1)
char_eps AS (
  SELECT
    tc.id AS char_id,
    GROUP_CONCAT(e.code, ', ') AS episode_codes
  FROM two_chars tc, json_each(tc.episodes) je
  JOIN episodes e
    ON e.id = json_extract(je.value, '$')
  GROUP BY tc.id
)
-- return one row for the location (context) and one per character
SELECT
  'location' AS kind,
  tl.name        AS location_name,
  tl.type        AS location_type,
  tl.dimension   AS location_dimension,
  NULL           AS character_name,
  NULL           AS character_status,
  NULL           AS character_species,
  NULL           AS character_type,
  NULL           AS character_gender,
  NULL           AS character_image,
  NULL           AS character_episodes,
  NULL           AS is_resident_of_location
FROM target_loc tl

UNION ALL

SELECT
  'character'    AS kind,
  tl.name        AS location_name,
  tl.type        AS location_type,
  tl.dimension   AS location_dimension,
  tcf.name       AS character_name,
  tcf.status     AS character_status,
  tcf.species    AS character_species,
  tcf.type       AS character_type,
  tcf.gender     AS character_gender,
  tcf.image      AS character_image,
  COALESCE(ce.episode_codes, '') AS character_episodes,
  tcf.is_resident_of_location
FROM two_chars_flagged tcf
LEFT JOIN char_eps ce
  ON ce.char_id = tcf.id
LEFT JOIN target_loc tl
  ON 1=1; 

    query_2 : Explain me about Baby Rick's 
    SQL_2 : SELECT *
    FROM characters AS c
    LEFT JOIN locations AS l
    ON c.location_id = l.id
    WHERE lower(c.name) = 'baby rick';
    """
)

ANSWER_SYSTEM_MESSAGE = (
    """You are a Rick and Morty guide. You will be provided with a context which contains some reference information provided to you for rick and morty universe.
    Summarise the context in detail and rick and morty narattor style so the user can make sense out of it and keep ot around the topic, you can add details from your own knowledge base but make sure to stick to the context provided, in priority.
    Dont refer to the columns or tables as Table1 or table 2 etc. in your response . Keep the response medium length and concise.
    Dont mention that you dont have enough data in any context """
)

#
# Optional environment overrides (useful for Docker/.env)
#
GRAPHQL_URL = os.getenv("GRAPHQL_URL", GRAPHQL_URL)
DB_PATH = os.getenv("DB_PATH", DB_PATH)
QUERY_FILE_PATH = os.getenv("QUERY_FILE_PATH", QUERY_FILE_PATH)
SCHEMA_JSON_PATH = os.getenv("SCHEMA_JSON_PATH", SCHEMA_JSON_PATH)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", OLLAMA_BASE_URL)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", OLLAMA_MODEL)
try:
    OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", OLLAMA_NUM_PREDICT))
except Exception:
    pass
try:
    OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", OLLAMA_TEMPERATURE))
except Exception:
    pass
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", OLLAMA_EMBED_MODEL)

