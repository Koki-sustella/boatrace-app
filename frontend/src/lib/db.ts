import * as duckdb from "@duckdb/duckdb-wasm";
import mvpWorker from "@duckdb/duckdb-wasm/dist/duckdb-browser-mvp.worker.js?url";
import ehWorker from "@duckdb/duckdb-wasm/dist/duckdb-browser-eh.worker.js?url";
import mvpWasm from "@duckdb/duckdb-wasm/dist/duckdb-mvp.wasm?url";
import ehWasm from "@duckdb/duckdb-wasm/dist/duckdb-eh.wasm?url";

const BUNDLES: duckdb.DuckDBBundles = {
  mvp: { mainModule: mvpWasm, mainWorker: mvpWorker },
  eh: { mainModule: ehWasm, mainWorker: ehWorker },
};

// Base URL for the published Parquet data: same-origin in production (fast,
// no CORS needed), the live deployed site during local dev (always fresh,
// no need to copy multi-MB data files into the frontend dev server).
// Must be a fully-qualified URL (scheme+host) -- DuckDB-WASM's httpfs runs in
// a Worker and does not resolve relative/path-only strings against the page.
const DATA_BASE = import.meta.env.DEV
  ? "https://koki-sustella.github.io/boatrace-app/data"
  : `${location.origin}${import.meta.env.BASE_URL}data`;

let dbPromise: Promise<duckdb.AsyncDuckDB> | null = null;
let connPromise: Promise<duckdb.AsyncDuckDBConnection> | null = null;

async function initDB(): Promise<duckdb.AsyncDuckDB> {
  const bundle = await duckdb.selectBundle(BUNDLES);
  const worker = new Worker(bundle.mainWorker!);
  const logger = new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING);
  const db = new duckdb.AsyncDuckDB(logger, worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  return db;
}

const TABLES = [
  "races", "entries", "program_entries", "racers", "racer_history",
  "grade_master", "agg_racer_course_month", "agg_racer_venue_course",
  "agg_racer_grade_month", "agg_venue_course_overall", "racer_rolling_form",
] as const;

async function getConn(): Promise<duckdb.AsyncDuckDBConnection> {
  if (!dbPromise) dbPromise = initDB();
  if (!connPromise) {
    connPromise = (async () => {
      const db = await dbPromise!;
      const conn = await db.connect();
      // Register each parquet as a DuckDB view over its HTTP(S) URL. DuckDB-WASM's
      // httpfs supports range requests, so only the row groups a query actually
      // touches get downloaded -- not the whole file every time.
      for (const t of TABLES) {
        await conn.query(
          `CREATE VIEW IF NOT EXISTS ${t} AS SELECT * FROM read_parquet('${DATA_BASE}/${t}.parquet')`
        );
      }
      // racer_current: each racer's latest known name/class/branch (racer_history
      // only has a row per *change*, so "current" = the most recent row).
      await conn.query(`
        CREATE VIEW IF NOT EXISTS racer_current AS
        SELECT * EXCLUDE (rn) FROM (
          SELECT *, row_number() OVER (PARTITION BY toroku_no ORDER BY year DESC, period DESC) AS rn
          FROM racer_history
        ) WHERE rn = 1
      `);
      // races_with_grade: grade isn't in the raw files, join the scraped schedule
      // (see docs/confirmed_layout.md); anything unmatched defaults to 一般.
      await conn.query(`
        CREATE VIEW IF NOT EXISTS races_with_grade AS
        SELECT r.*, COALESCE(g.grade, '一般') AS grade
        FROM races r LEFT JOIN grade_master g USING (venue_code, date)
      `);
      await conn.query(`
        CREATE VIEW IF NOT EXISTS entries_enriched AS
        SELECT e.*, rg.title, rg.grade, rg.weather, rg.wind_dir, rg.wind_speed_m, rg.wave_cm, rg.distance_m
        FROM entries e JOIN races_with_grade rg USING (venue_code, date, race_no)
      `);
      return conn;
    })();
  }
  return connPromise;
}

/** Run a SQL query and return rows as plain objects. */
export async function query<T = Record<string, unknown>>(sql: string): Promise<T[]> {
  const conn = await getConn();
  const result = await conn.query(sql);
  return result.toArray().map((row) => row.toJSON() as T);
}

export function escapeSqlString(s: string): string {
  return s.replace(/'/g, "''");
}
