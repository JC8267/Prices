# price_tracker.py  ─────────────────────────────────────────────
import sqlite3, datetime, pathlib

DB = "prices.sqlite"

def init_db() -> None:
    """Create table once per project."""
    pathlib.Path(DB).touch(exist_ok=True)
    with sqlite3.connect(DB) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            art_no        TEXT,
            competitor    TEXT,
            url           TEXT,
            fetched_at    TEXT,
            price         REAL,
            currency      TEXT,
            competitor_sku TEXT,  /* Added field for competitor's SKU */
            PRIMARY KEY (art_no, competitor, fetched_at)
        )""")

def _save(art: str, comp: str, url: str,
          price: float, cur: str = "USD", comp_sku: str = None) -> None:
    """Insert one row; ignore dupes for the same day."""
    fetched_at = datetime.date.today().isoformat()
    with sqlite3.connect(DB) as conn:
        conn.execute("""
            INSERT OR IGNORE INTO prices
            VALUES (?,?,?,?,?,?,?)
        """, (art, comp, url, fetched_at, price, cur, comp_sku))