import csv
import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()

DB_PATH = "cryptos.db"                # Base de datos existente
CSV_TICKERS = os.environ.get("CSV_TICKERS", "tickers.csv")

def crear_tabla_tickers(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tickers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL UNIQUE,
            vigilar BOOLEAN NOT NULL DEFAULT 1,
            nombre TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    print("✅ Tabla 'tickers' creada/verificada en cryptos.db")

def migrar_csv_a_sqlite():
    if not os.path.exists(CSV_TICKERS):
        print(f"⚠️ No se encuentra {CSV_TICKERS}, omitiendo migración. Puedes insertar tickers manualmente.")
        return

    conn = sqlite3.connect(DB_PATH)
    crear_tabla_tickers(conn)
    cursor = conn.cursor()

    with open(CSV_TICKERS, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        # Normalizar nombres de columnas a minúsculas
        reader.fieldnames = [col.lower() for col in reader.fieldnames]
        for row in reader:
            ticker = row.get('ticker', '').strip()
            if not ticker:
                continue
            vigilar = row.get('vigilar', 'True').strip().lower() in ('true', '1', 'yes', 'y')
            nombre = row.get('nombre', '') or None
            cursor.execute("""
                INSERT OR REPLACE INTO tickers (ticker, vigilar, nombre)
                VALUES (?, ?, ?)
            """, (ticker, vigilar, nombre))
    conn.commit()
    conn.close()
    print(f"✅ Migración completada desde {CSV_TICKERS} a {DB_PATH} (tabla tickers)")

if __name__ == "__main__":
    migrar_csv_a_sqlite()