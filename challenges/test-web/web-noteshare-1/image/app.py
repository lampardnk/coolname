"""
NoteShare - A university note-sharing platform with 5 vulnerabilities.

Flag 1 (robots.txt):       GET /robots.txt
Flag 2 (cookie auth):      Change role cookie from "user" to "admin"
Flag 3 (SQL injection):    Login form with string-formatted query
Flag 4 (SSTI):             Jinja2 render_template_string on search input
Flag 5 (path traversal):   /download?file=../../../flag.txt
"""
import os
import sqlite3
from flask import (
    Flask, request, render_template_string, make_response,
    send_file, redirect,
)

app = Flask(__name__)

FLAG1 = os.environ.get("FLAG1", "CTF{default_flag1}")
FLAG2 = os.environ.get("FLAG2", "CTF{default_flag2}")
FLAG3 = os.environ.get("FLAG3", "CTF{default_flag3}")
FLAG4 = os.environ.get("FLAG4", "CTF{default_flag4}")
FLAG5 = os.environ.get("FLAG5", "CTF{default_flag5}")
app.config["FLAG"] = FLAG4

DB = "/tmp/notes.db"

# ── database ────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, role TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY, title TEXT, content TEXT, owner TEXT, filename TEXT)""")
    c.execute("INSERT OR IGNORE INTO users VALUES (1,'admin','n0t3sh4r3_s3cr3t!','admin')")
    c.execute("INSERT OR IGNORE INTO users VALUES (2,'guest','guest','user')")
    c.execute("INSERT OR IGNORE INTO notes VALUES (1,'Welcome to NoteShare','Welcome! Share and browse notes with your classmates.','admin',NULL)")
    c.execute("INSERT OR IGNORE INTO notes VALUES (2,'Admin Credentials Backup',?,'admin',NULL)", (FLAG3,))
    c.execute("INSERT OR IGNORE INTO notes VALUES (3,'CS101 Lecture 1','Introduction to Algorithms and Data Structures. See attachment.','guest','lecture1.txt')")
    c.execute("INSERT OR IGNORE INTO notes VALUES (4,'CS101 Lecture 2','Sorting algorithms: bubble, merge, quick sort.','guest','lecture2.txt')")
    conn.commit()
    conn.close()

# write flag5 to /flag.txt at startup
with open("/flag.txt", "w") as f:
    f.write(FLAG5 + "\n")

os.makedirs("/app/uploads", exist_ok=True)
for name, text in [
    ("lecture1.txt", "CS101 Lecture 1\n\nTopics: Big-O, arrays, linked lists.\n"),
    ("lecture2.txt", "CS101 Lecture 2\n\nTopics: Bubble sort, merge sort, quicksort.\n"),
]:
    with open(f"/app/uploads/{name}", "w") as f:
        f.write(text)

init_db()

# ── styles ──────────────────────────────────────────────────────────────────

STYLE = """
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#c9d1d9}
a{color:#58a6ff;text-decoration:none}a:hover{text-decoration:underline}
header{background:#161b22;border-bottom:1px solid #30363d;padding:14px 24px;display:flex;align-items:center;justify-content:space-between}
header h1{font-size:1.2rem;color:#f0f6fc}header h1 span{color:#58a6ff}
nav a{margin-left:16px;color:#8b949e;font-size:.9rem}nav a:hover{color:#f0f6fc}
main{max-width:860px;margin:32px auto;padding:0 20px}
h2{color:#f0f6fc;margin-bottom:16px;font-size:1.3rem}
.card{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:20px;margin-bottom:16px}
.card h3{color:#58a6ff;margin-bottom:8px}
.card p{color:#8b949e;font-size:.9rem}
.badge{display:inline-block;font-size:.75rem;padding:2px 8px;border-radius:12px;margin-left:8px}
.badge-admin{background:#f8514933;color:#f85149;border:1px solid #f8514966}
.badge-user{background:#3fb95033;color:#3fb950;border:1px solid #3fb95066}
input,textarea{width:100%;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:10px 12px;border-radius:6px;font-size:.9rem;margin-bottom:12px}
input:focus,textarea:focus{outline:none;border-color:#58a6ff}
textarea{height:100px;font-family:monospace;resize:vertical}
button,.btn{background:#238636;color:#fff;border:none;padding:10px 20px;border-radius:6px;cursor:pointer;font-size:.9rem;font-weight:600}
button:hover,.btn:hover{background:#2ea043}
.btn-sm{padding:6px 12px;font-size:.8rem}
.error{background:#f8514922;border:1px solid #f8514966;color:#f85149;padding:12px;border-radius:6px;margin-bottom:16px}
.success{background:#23863622;border:1px solid #23863666;color:#3fb950;padding:12px;border-radius:6px;margin-bottom:16px}
.output{background:#161b22;border:1px solid #30363d;padding:16px;border-radius:6px;margin-top:16px;white-space:pre-wrap;font-family:monospace;font-size:.85rem}
table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid #21262d}
th{color:#8b949e;font-size:.8rem;text-transform:uppercase;letter-spacing:.5px}
.dl{color:#58a6ff;font-size:.85rem}
footer{text-align:center;color:#484f58;font-size:.8rem;margin-top:48px;padding:24px}
</style>
"""

NAV = """
<nav>
  <a href="/dashboard">Dashboard</a>
  <a href="/search">Search</a>
  <a href="/login">Logout</a>
</nav>
"""

# ── Vuln 1: robots.txt ─────────────────────────────────────────────────────

@app.route("/robots.txt")
def robots():
    return (
        "User-agent: *\n"
        "Disallow: /admin\n"
        "Disallow: /secret\n"
        f"# TODO: remove before production -- {FLAG1}\n"
    ), 200, {"Content-Type": "text/plain"}

# ── routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect("/login")

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        # Vuln 3: SQL injection via string formatting
        conn = get_db()
        query = f"SELECT * FROM users WHERE username='{username}' AND password='{password}'"
        try:
            row = conn.execute(query).fetchone()
            if row:
                resp = make_response(redirect("/dashboard"))
                resp.set_cookie("user", row["username"])
                # Vuln 2: role stored in client-side cookie
                resp.set_cookie("role", row["role"])
                return resp
            error = "Invalid username or password."
        except Exception as e:
            error = f"Database error: {e}"
        finally:
            conn.close()

    return render_template_string("""<!DOCTYPE html><html><head><title>NoteShare - Login</title>""" + STYLE + """</head><body>
<header><h1><span>Note</span>Share</h1></header>
<main>
  <div class="card" style="max-width:400px;margin:60px auto">
    <h2>Sign in</h2>
    <p style="color:#8b949e;margin-bottom:20px">Access your shared notes</p>
    {% if error %}<div class="error">{{ error }}</div>{% endif %}
    <form method="POST">
      <input name="username" placeholder="Username" required autofocus>
      <input name="password" type="password" placeholder="Password" required>
      <button style="width:100%">Sign in</button>
    </form>
    <p style="color:#484f58;font-size:.8rem;margin-top:12px">Hint: guest / guest</p>
  </div>
</main></body></html>""", error=error)


@app.route("/dashboard")
def dashboard():
    user = request.cookies.get("user")
    role = request.cookies.get("role")
    if not user:
        return redirect("/login")

    conn = get_db()
    # Vuln 2: changing role cookie to "admin" reveals all notes + flag
    if role == "admin":
        notes = conn.execute("SELECT * FROM notes ORDER BY id").fetchall()
    else:
        notes = conn.execute("SELECT * FROM notes WHERE owner=? OR owner='admin' AND id=1",
                             (user,)).fetchall()
    conn.close()

    return render_template_string("""<!DOCTYPE html><html><head><title>NoteShare - Dashboard</title>""" + STYLE + """</head><body>
<header><h1><span>Note</span>Share</h1>""" + NAV + """</header>
<main>
  <h2>Dashboard <span class="badge {{ 'badge-admin' if role=='admin' else 'badge-user' }}">{{ role }}</span></h2>
  {% if role == 'admin' %}
  <div class="success">Admin access granted. {{ flag2 }}</div>
  {% endif %}
  <div class="card">
    <table>
      <tr><th>#</th><th>Title</th><th>Owner</th><th>File</th></tr>
      {% for n in notes %}
      <tr>
        <td>{{ n['id'] }}</td>
        <td>{{ n['title'] }}</td>
        <td>{{ n['owner'] }}</td>
        <td>{% if n['filename'] %}<a class="dl" href="/download?file={{ n['filename'] }}">{{ n['filename'] }}</a>{% else %}-{% endif %}</td>
      </tr>
      {% endfor %}
    </table>
  </div>
  {% if role == 'admin' %}
  <div class="card">
    <h3>Admin Notes</h3>
    {% for n in notes %}
    <p style="margin-bottom:8px"><strong>{{ n['title'] }}:</strong> {{ n['content'] }}</p>
    {% endfor %}
  </div>
  {% endif %}
</main>
<footer>NoteShare v1.0 &mdash; University CS Department</footer>
</body></html>""", notes=notes, role=role, flag2=FLAG2)


# Vuln 4: SSTI in search
@app.route("/search", methods=["GET"])
def search():
    user = request.cookies.get("user")
    if not user:
        return redirect("/login")

    q = request.args.get("q", "")
    result = ""
    if q:
        # SSTI: user input rendered directly in template
        tpl = '<div class="output">Results for: ' + q + "</div>"
        try:
            result = render_template_string(tpl)
        except Exception as e:
            result = f'<div class="output" style="border-color:#f85149">Error: {e}</div>'

    return render_template_string("""<!DOCTYPE html><html><head><title>NoteShare - Search</title>""" + STYLE + """</head><body>
<header><h1><span>Note</span>Share</h1>""" + NAV + """</header>
<main>
  <h2>Search Notes</h2>
  <div class="card">
    <form method="GET">
      <input name="q" placeholder="Search notes..." value="{{ query }}">
      <button>Search</button>
    </form>
  </div>
  {{ result | safe }}
</main>
<footer>NoteShare v1.0 &mdash; University CS Department</footer>
</body></html>""", query=q, result=result)


# Vuln 5: path traversal
@app.route("/download")
def download():
    user = request.cookies.get("user")
    if not user:
        return redirect("/login")

    filename = request.args.get("file", "")
    if not filename:
        return "Missing file parameter", 400

    # Vulnerable: no sanitization on filename
    filepath = os.path.join("/app/uploads", filename)
    try:
        return send_file(filepath)
    except Exception:
        return "File not found", 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
