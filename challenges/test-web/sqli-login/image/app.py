"""
SQL Injection — login bypass challenge.

The login form builds its SQL query via string formatting.
The admin's secret (the flag) is stored in the database.
"""
import sqlite3
import os
from flask import Flask, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = os.urandom(32)
DB = "/tmp/auth.db"


def init_db():
    conn = sqlite3.connect(DB)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            id       INTEGER PRIMARY KEY,
            username TEXT UNIQUE,
            password TEXT,
            secret   TEXT
        );
        INSERT OR IGNORE INTO accounts VALUES
            (1, 'admin', 'hunter2', 'CTF{sql_1nject10n_bypasses_auth}'),
            (2, 'guest', 'guest',   'nothing interesting here');
    """)
    conn.commit()
    conn.close()


STYLE = """
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Courier New', monospace; background: #1a1a2e; color: #eee;
         display: flex; align-items: center; justify-content: center; height: 100vh; }
  .box { background: #16213e; border: 1px solid #0f3460; border-radius: 8px;
         padding: 40px; width: 380px; }
  h2 { color: #e94560; margin-bottom: 24px; font-size: 1.4rem; }
  label { display: block; color: #aaa; font-size: 0.85rem; margin-bottom: 4px; }
  input { width: 100%; padding: 10px; background: #0f3460; border: 1px solid #e94560;
          color: #eee; border-radius: 4px; margin-bottom: 16px; font-family: inherit; }
  button { width: 100%; padding: 12px; background: #e94560; color: white; border: none;
           border-radius: 4px; cursor: pointer; font-size: 1rem; font-family: inherit; }
  .msg { padding: 10px 14px; border-radius: 4px; margin-bottom: 16px; font-size: 0.9rem; }
  .error { background: #2a0a0a; border: 1px solid #e94560; color: #ff8080; }
  .success { background: #0a2a0a; border: 1px solid #3fb950; color: #3fb950; word-break: break-all; }
  .hint { color: #555; font-size: 0.75rem; margin-top: 20px; text-align: center; }
</style>
"""


@app.route("/", methods=["GET", "POST"])
def login():
    msg = ""
    cls = ""
    if request.method == "POST":
        u = request.form.get("username", "")
        p = request.form.get("password", "")
        try:
            conn = sqlite3.connect(DB)
            # INTENTIONALLY VULNERABLE — string interpolation
            query = f"SELECT * FROM accounts WHERE username='{u}' AND password='{p}'"
            row = conn.execute(query).fetchone()
            conn.close()
        except Exception as e:
            msg = f"DB error: {e}"
            cls = "error"
            row = None
        if row:
            msg = f"Welcome, {row[1]}! Your secret: {row[3]}"
            cls = "success"
        elif not msg:
            msg = "Invalid username or password."
            cls = "error"

    msg_html = f'<div class="msg {cls}">{msg}</div>' if msg else ""
    return f"""<!DOCTYPE html>
<html><head><title>Secure Auth Portal</title>{STYLE}</head>
<body><div class="box">
  <h2>🔐 Secure Auth Portal</h2>
  {msg_html}
  <form method="POST">
    <label>Username</label>
    <input name="username" autocomplete="off" placeholder="guest">
    <label>Password</label>
    <input name="password" type="password" placeholder="••••••">
    <button>Login</button>
  </form>
  <p class="hint">Powered by SQLite {sqlite3.sqlite_version}</p>
</div></body></html>"""


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8080)
