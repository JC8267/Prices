
def init_db():
    with sqlite3.connect(DB) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            art_no      TEXT,
            competitor  TEXT,
            url         TEXT,
            fetched_at  TEXT,
            price       REAL,
            currency    TEXT,
            PRIMARY KEY (art_no, competitor, fetched_at)
        )""")
