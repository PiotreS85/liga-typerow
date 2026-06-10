#!/usr/bin/env python3
"""
Liga Typerów — serwer z PostgreSQL (Railway) lub SQLite (lokalnie)
"""
import http.server
import urllib.request
import urllib.error
import urllib.parse
import json
import os
import threading
import webbrowser
import time

API_KEY  = '3d1551c507ce499eae50ecd9894d0058'
API_BASE = 'https://api.football-data.org/v4'
PORT     = int(os.environ.get('PORT', 80))
DATABASE_URL = os.environ.get('DATABASE_URL', '')  # Railway ustawia automatycznie

# ── BAZA DANYCH ───────────────────────────────────────────────────────────────
USE_POSTGRES = bool(DATABASE_URL)
db_lock = threading.Lock()

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    def get_db():
        return psycopg2.connect(DATABASE_URL, sslmode='require')
    PH = '%s'   # placeholder PostgreSQL
else:
    import sqlite3
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'liga.db')
    def get_db():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    PH = '?'    # placeholder SQLite

def init_db():
    with db_lock:
        conn = get_db()
        cur  = conn.cursor()
        if USE_POSTGRES:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS players (
                    name TEXT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT NOW()
                )''')
        else:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS players (
                    name TEXT PRIMARY KEY,
                    created_at TEXT DEFAULT (datetime('now'))
                )''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS matches (
                id TEXT PRIMARY KEY,
                ta TEXT, tb TEXT,
                group_name TEXT,
                date TEXT,
                status TEXT,
                stage TEXT,
                sa INTEGER DEFAULT NULL,
                sb INTEGER DEFAULT NULL
            )''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS bets (
                match_id TEXT,
                player   TEXT,
                a INTEGER,
                b INTEGER,
                PRIMARY KEY (match_id, player)
            )''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )''')
        # Wartości domyślne
        if USE_POSTGRES:
            cur.execute("INSERT INTO settings VALUES ('pin','1234') ON CONFLICT DO NOTHING")
            cur.execute("INSERT INTO settings VALUES ('last_sync','') ON CONFLICT DO NOTHING")
        else:
            cur.execute("INSERT OR IGNORE INTO settings VALUES ('pin','1234')")
            cur.execute("INSERT OR IGNORE INTO settings VALUES ('last_sync','')")
        conn.commit()
        conn.close()

def rows_as_dicts(cursor):
    """Konwertuje wiersze do listy słowników (dla obu sterowników)."""
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]

def upsert_match(cur, m):
    """Wstaw lub zaktualizuj mecz — obsługa obu baz."""
    if USE_POSTGRES:
        cur.execute('''
            INSERT INTO matches (id,ta,tb,group_name,date,status,stage,sa,sb)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
                ta=CASE WHEN EXCLUDED.ta<>'?' THEN EXCLUDED.ta ELSE matches.ta END,
                tb=CASE WHEN EXCLUDED.tb<>'?' THEN EXCLUDED.tb ELSE matches.tb END,
                group_name=EXCLUDED.group_name,
                date=EXCLUDED.date,
                status=EXCLUDED.status,
                stage=EXCLUDED.stage,
                sa=COALESCE(EXCLUDED.sa, matches.sa),
                sb=COALESCE(EXCLUDED.sb, matches.sb)
        ''', (m['id'],m['ta'],m['tb'],m.get('group'),m.get('date'),
              m.get('status'),m.get('stage'),m.get('sa'),m.get('sb')))
    else:
        existing = cur.execute('SELECT id,ta,tb FROM matches WHERE id=?',(m['id'],)).fetchone()
        if existing:
            cur.execute('''UPDATE matches SET
                ta=CASE WHEN ? <> '?' THEN ? ELSE ta END,
                tb=CASE WHEN ? <> '?' THEN ? ELSE tb END,
                group_name=?,date=?,status=?,stage=?,
                sa=COALESCE(?,sa),sb=COALESCE(?,sb)
                WHERE id=?''',
                (m['ta'],m['ta'],m['tb'],m['tb'],
                 m.get('group'),m.get('date'),m.get('status'),m.get('stage'),
                 m.get('sa'),m.get('sb'),m['id']))
        else:
            cur.execute('INSERT INTO matches VALUES (?,?,?,?,?,?,?,?,?)',
                (m['id'],m['ta'],m['tb'],m.get('group'),m.get('date'),
                 m.get('status'),m.get('stage'),m.get('sa'),m.get('sb')))

# ── HANDLER ───────────────────────────────────────────────────────────────────
class Handler(http.server.SimpleHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"  {self.command} {self.path}")

    def do_GET(self):
        if self.path == '/':
            self.path = '/liga_typerow.html'
        if self.path.startswith('/api/football/'):
            self._proxy(self.path[13:])
        elif self.path.startswith('/db/'):
            self._db_get()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path.startswith('/db/'):
            length = int(self.headers.get('Content-Length', 0))
            body   = self.rfile.read(length)
            try:    data = json.loads(body) if body else {}
            except: data = {}
            self._db_post(data)
        else:
            self._send_json({'error': 'Not found'}, 404)

    def do_DELETE(self):
        if self.path.startswith('/db/'):
            self._db_delete()
        else:
            self._send_json({'error': 'Not found'}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    # ── PROXY ─────────────────────────────────────────────────────────────────
    def _proxy(self, api_path):
        target = API_BASE + api_path
        try:
            req = urllib.request.Request(target, headers={'X-Auth-Token': API_KEY})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data, code = resp.read(), resp.getcode()
        except urllib.error.HTTPError as e:
            data, code = e.read(), e.code
        except Exception as e:
            data, code = json.dumps({'error': str(e)}).encode(), 500
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    # ── DB GET ─────────────────────────────────────────────────────────────────
    def _db_get(self):
        path = self.path[4:].split('?')[0].rstrip('/')
        try:
            with db_lock:
                conn = get_db()
                cur  = conn.cursor()

                if path == 'state':
                    cur.execute('SELECT name FROM players ORDER BY created_at')
                    players = [r[0] for r in cur.fetchall()]

                    cur.execute('SELECT * FROM matches ORDER BY date')
                    matches = rows_as_dicts(cur)

                    cur.execute('SELECT match_id,player,a,b FROM bets')
                    bets = {f"{r['match_id']}_{r['player']}": {'a':r['a'],'b':r['b']}
                            for r in rows_as_dicts(cur)}

                    cur.execute("SELECT value FROM settings WHERE key='last_sync'")
                    row = cur.fetchone()
                    sync = row[0] if row else ''
                    conn.close()
                    return self._send_json({'players':players,'matches':matches,'bets':bets,'lastSync':sync})

            conn.close()
        except Exception as e:
            return self._send_json({'error': str(e)}, 500)
        self._send_json({'error': 'Not found'}, 404)

    # ── DB POST ────────────────────────────────────────────────────────────────
    def _db_post(self, data):
        path = self.path[4:].rstrip('/')
        try:
            with db_lock:
                conn = get_db()
                cur  = conn.cursor()

                # Dodaj gracza
                if path == 'players':
                    name = (data.get('name') or '').strip()
                    if not name:
                        conn.close(); return self._send_json({'error':'Brak imienia'},400)
                    try:
                        if USE_POSTGRES:
                            cur.execute('INSERT INTO players(name) VALUES (%s) ON CONFLICT DO NOTHING RETURNING name', (name,))
                            if cur.fetchone() is None:
                                conn.close(); return self._send_json({'error':'Gracz już istnieje'},409)
                        else:
                            cur.execute('INSERT INTO players(name) VALUES (?)', (name,))
                        conn.commit(); conn.close()
                        return self._send_json({'ok':True,'name':name})
                    except Exception as e:
                        conn.close(); return self._send_json({'error':str(e)},409)

                # Synchronizacja meczów
                if path == 'matches/sync':
                    matches = data.get('matches', [])
                    added = updated = 0
                    for m in matches:
                        if USE_POSTGRES:
                            cur.execute('SELECT id FROM matches WHERE id=%s',(m['id'],))
                        else:
                            cur.execute('SELECT id FROM matches WHERE id=?',(m['id'],))
                        existed = cur.fetchone() is not None
                        upsert_match(cur, m)
                        if existed: updated += 1
                        else:       added   += 1
                    if USE_POSTGRES:
                        cur.execute("UPDATE settings SET value=NOW()::text WHERE key='last_sync'")
                    else:
                        cur.execute("UPDATE settings SET value=datetime('now') WHERE key='last_sync'")
                    conn.commit(); conn.close()
                    return self._send_json({'ok':True,'added':added,'updated':updated})

                # Dodaj jeden mecz
                if path == 'matches':
                    m = data
                    try:
                        if USE_POSTGRES:
                            cur.execute('INSERT INTO matches VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                                (m['id'],m['ta'],m['tb'],m.get('group'),m.get('date'),m.get('status','SCHEDULED'),m.get('stage',''),None,None))
                        else:
                            cur.execute('INSERT INTO matches VALUES (?,?,?,?,?,?,?,?,?)',
                                (m['id'],m['ta'],m['tb'],m.get('group'),m.get('date'),m.get('status','SCHEDULED'),m.get('stage',''),None,None))
                        conn.commit(); conn.close()
                        return self._send_json({'ok':True})
                    except Exception as e:
                        conn.close(); return self._send_json({'error':str(e)},409)

                # Zapisz typ
                if path == 'bets':
                    mid,player,a,b = data.get('match_id'),data.get('player'),data.get('a'),data.get('b')
                    if None in (mid,player,a,b):
                        conn.close(); return self._send_json({'error':'Niepełne dane'},400)
                    if USE_POSTGRES:
                        cur.execute('INSERT INTO bets VALUES (%s,%s,%s,%s) ON CONFLICT(match_id,player) DO UPDATE SET a=%s,b=%s',
                                    (mid,player,a,b,a,b))
                    else:
                        cur.execute('INSERT OR REPLACE INTO bets VALUES (?,?,?,?)',(mid,player,a,b))
                    conn.commit(); conn.close()
                    return self._send_json({'ok':True})

                # Zapisz wynik
                if path == 'scores':
                    mid,sa,sb = data.get('match_id'),data.get('sa'),data.get('sb')
                    if USE_POSTGRES:
                        cur.execute("UPDATE matches SET sa=%s,sb=%s,status='FINISHED' WHERE id=%s",(sa,sb,mid))
                    else:
                        cur.execute("UPDATE matches SET sa=?,sb=?,status='FINISHED' WHERE id=?",(sa,sb,mid))
                    conn.commit(); conn.close()
                    return self._send_json({'ok':True})

                # Weryfikacja PIN
                if path == 'pin/verify':
                    if USE_POSTGRES:
                        cur.execute("SELECT value FROM settings WHERE key='pin'")
                    else:
                        cur.execute("SELECT value FROM settings WHERE key='pin'")
                    row = cur.fetchone()
                    stored = row[0] if row else '1234'
                    conn.close()
                    return self._send_json({'ok': str(data.get('pin','')) == str(stored)})

                # Zmień PIN
                if path == 'pin':
                    new_pin = str(data.get('pin',''))
                    if len(new_pin) < 3:
                        conn.close(); return self._send_json({'error':'PIN za krótki'},400)
                    if USE_POSTGRES:
                        cur.execute("UPDATE settings SET value=%s WHERE key='pin'",(new_pin,))
                    else:
                        cur.execute("UPDATE settings SET value=? WHERE key='pin'",(new_pin,))
                    conn.commit(); conn.close()
                    return self._send_json({'ok':True})

                # Reset ligi
                if path == 'reset':
                    cur.execute('DELETE FROM bets')
                    cur.execute('DELETE FROM matches')
                    cur.execute('DELETE FROM players')
                    if USE_POSTGRES:
                        cur.execute("UPDATE settings SET value='' WHERE key='last_sync'")
                        cur.execute("UPDATE settings SET value='1234' WHERE key='pin'")
                    else:
                        cur.execute("UPDATE settings SET value='' WHERE key='last_sync'")
                        cur.execute("UPDATE settings SET value='1234' WHERE key='pin'")
                    conn.commit(); conn.close()
                    return self._send_json({'ok':True})

                conn.close()
        except Exception as e:
            return self._send_json({'error': str(e)}, 500)
        self._send_json({'error': 'Not found'}, 404)

    # ── DB DELETE ──────────────────────────────────────────────────────────────
    def _db_delete(self):
        parts = self.path[4:].rstrip('/').split('/')
        try:
            with db_lock:
                conn = get_db()
                cur  = conn.cursor()
                if len(parts) == 2 and parts[0] == 'players':
                    name = urllib.parse.unquote(parts[1])
                    cur.execute(f'DELETE FROM bets WHERE player={PH}', (name,))
                    cur.execute(f'DELETE FROM players WHERE name={PH}', (name,))
                    conn.commit(); conn.close()
                    return self._send_json({'ok':True})
                if len(parts) == 2 and parts[0] == 'matches':
                    mid = urllib.parse.unquote(parts[1])
                    cur.execute(f'DELETE FROM bets WHERE match_id={PH}', (mid,))
                    cur.execute(f'DELETE FROM matches WHERE id={PH}', (mid,))
                    conn.commit(); conn.close()
                    return self._send_json({'ok':True})
                conn.close()
        except Exception as e:
            return self._send_json({'error': str(e)}, 500)
        self._send_json({'error': 'Not found'}, 404)

    # ── HELPERS ───────────────────────────────────────────────────────────────
    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    init_db()
    is_cloud = 'PORT' in os.environ

    try:
        server = http.server.HTTPServer(('', PORT), Handler)
    except OSError:
        fallback = 8080
        print(f'Port {PORT} zajęty, próbuję {fallback}...')
        server = http.server.HTTPServer(('', fallback), Handler)
        PORT_actual = fallback
    else:
        PORT_actual = PORT

    if is_cloud:
        db_type = 'PostgreSQL' if USE_POSTGRES else 'SQLite'
        print(f'Serwer działa na porcie {PORT_actual} [{db_type}]')
    else:
        url = f'http://localhost:{PORT_actual}'
        print('=' * 50)
        print('  Liga Typerów — Mundial 2026')
        print(f'  Adres: {url}')
        print(f'  Baza:  {"PostgreSQL" if USE_POSTGRES else "SQLite (lokalna)"}')
        print('  Aby zatrzymać: Ctrl+C')
        print('=' * 50)
        def open_browser():
            time.sleep(1.5)
            webbrowser.open(url)
        threading.Thread(target=open_browser, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nSerwer zatrzymany.')

if __name__ == '__main__':
    main()
