import csv
import sqlite3
import os
import sys
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

CRYPTOS_CSV = os.environ.get("CRYPTOS_CSV", "cryptos.csv")
DB_PATH = "cryptos.db"

def crear_tabla_y_migrar():
    print(f"🔍 Buscando CSV en: {os.path.abspath(CRYPTOS_CSV)}")
    
    # Verificar existencia del CSV
    if not os.path.exists(CRYPTOS_CSV):
        print(f"❌ ERROR: No se encuentra el archivo {CRYPTOS_CSV}")
        print("Asegúrate de que el archivo está en este directorio.")
        return False
    
    # Verificar que el CSV no está vacío
    if os.path.getsize(CRYPTOS_CSV) == 0:
        print(f"❌ ERROR: El archivo {CRYPTOS_CSV} está vacío")
        return False
    
    # Conectar a la base de datos (se creará automáticamente)
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        print(f"✅ Conectado a {DB_PATH}")
    except sqlite3.Error as e:
        print(f"❌ Error al conectar a SQLite: {e}")
        return False
    
    # Crear tabla
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cryptos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL UNIQUE,
            name TEXT,
            upper REAL,
            lower REAL,
            active BOOLEAN
        )
    """)
    print("✅ Tabla 'cryptos' creada/verificada")
    
    # Leer CSV
    try:
        with open(CRYPTOS_CSV, newline='', encoding='utf-8') as csvfile:
            # Detectar si hay BOM (Byte Order Mark)
            first_chars = csvfile.read(3)
            if first_chars == '\xef\xbb\xbf':
                print("⚠️ Se detectó BOM UTF-8, reabriendo con encoding 'utf-8-sig'")
                csvfile.close()
                csvfile = open(CRYPTOS_CSV, newline='', encoding='utf-8-sig')
            else:
                csvfile.seek(0)
            
            reader = csv.DictReader(csvfile)
            
            # Mostrar columnas detectadas
            print(f"📋 Columnas detectadas en CSV: {reader.fieldnames}")
            
            # Verificar columnas necesarias
            required = ['symbol', 'name', 'upper', 'lower', 'active']
            missing = [col for col in required if col not in reader.fieldnames]
            if missing:
                print(f"❌ Faltan columnas requeridas: {missing}")
                return False
            
            filas_insertadas = 0
            for row in reader:
                # Convertir 'active' a booleano
                active_raw = row.get('active', 'false').strip().lower()
                active_value = active_raw in ('true', '1', 'yes', 'y')
                
                # Convertir upper y lower a float (o None)
                upper_val = None
                lower_val = None
                if row.get('upper') and row['upper'].strip():
                    try:
                        upper_val = float(row['upper'])
                    except ValueError:
                        print(f"⚠️ Valor 'upper' inválido para {row.get('symbol')}: {row['upper']}")
                if row.get('lower') and row['lower'].strip():
                    try:
                        lower_val = float(row['lower'])
                    except ValueError:
                        print(f"⚠️ Valor 'lower' inválido para {row.get('symbol')}: {row['lower']}")
                
                # Insertar (ignorar duplicados por symbol)
                try:
                    cursor.execute("""
                        INSERT OR IGNORE INTO cryptos (symbol, name, upper, lower, active)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        row.get('symbol'),
                        row.get('name'),
                        upper_val,
                        lower_val,
                        active_value
                    ))
                    if cursor.rowcount > 0:
                        filas_insertadas += 1
                except sqlite3.Error as e:
                    print(f"❌ Error al insertar {row.get('symbol')}: {e}")
            
            conn.commit()
            print(f"✅ Migración completada: {filas_insertadas} filas insertadas en {DB_PATH}")
            
            # Mostrar contenido de la tabla
            cursor.execute("SELECT COUNT(*) FROM cryptos")
            total = cursor.fetchone()[0]
            print(f"📊 Total de registros en la tabla: {total}")
            
            return True
            
    except Exception as e:
        print(f"❌ Error inesperado: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    if crear_tabla_y_migrar():
        print("\n🎉 ¡Listo! Ahora puedes ejecutar el vigilante y sqlite-web.")
    else:
        print("\n⚠️ La migración falló. Revisa los mensajes de error arriba.")
        sys.exit(1)