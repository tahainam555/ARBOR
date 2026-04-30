import os, sqlite3
p = os.path.join(os.path.dirname(__file__), '..', 'data', 'crm.db')
p = os.path.normpath(os.path.abspath(p))
print('crm_db_path:', p)
print('exists:', os.path.exists(p))
if not os.path.exists(p):
    print('DB not found; exiting')
    raise SystemExit(0)
conn = sqlite3.connect(p)
cur = conn.cursor()
print('\nTables:')
for row in cur.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view')"):
    print(' -', row)

print('\nUsers:')
try:
    for r in cur.execute('SELECT user_id, name, risk_profile, investment_goals, watchlist FROM users'):
        print(r)
except Exception as e:
    print('users select error:', e)

print('\nInteractions:')
try:
    for r in cur.execute('SELECT id, user_id, session_id, summary, timestamp FROM interactions'):
        print(r)
except Exception as e:
    print('interactions select error:', e)

conn.close()
