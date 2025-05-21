import sqlite3, datetime

DB = "prices.sqlite"

def _save(art_no: str,
          competitor: str,
          url: str,
          sku: str,
          price: float,
          currency: str):
    """
    Inserts or replaces…
    """
    today = datetime.date.today().isoformat()
    with sqlite3.connect(DB) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO prices
               (art_no, competitor, url, sku, date, price, currency)
            VALUES (?,?,?,?,?,?,?)
            """,
            (art_no, competitor, url, sku, today, price, currency)
        )
        conn.commit()

def init_db():
    """Create the `prices` table if it doesn't already exist."""
    with sqlite3.connect(DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                art_no     TEXT,
                competitor TEXT,
                url        TEXT,
                sku        TEXT,
                date       TEXT,
                price      REAL,
                currency   TEXT,
                PRIMARY KEY (art_no, competitor, url, date)
            )
        """)
        conn.commit()
