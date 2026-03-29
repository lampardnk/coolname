/**
 * JWT Algorithm Confusion — admin panel challenge.
 *
 * The server issues HS256 tokens but manually checks the `alg` header.
 * If alg == "none", it skips signature verification entirely — a classic
 * misconfiguration allowing unsigned token forgery.
 *
 * Exploit:
 *   1. POST /login {"username":"guest","password":"guest123"} → get HS256 JWT
 *   2. Decode header + payload (base64url), change role to "admin", set alg to "none"
 *   3. Re-encode: base64url(header) + "." + base64url(payload) + "."  (empty sig)
 *   4. GET /admin  Authorization: Bearer <forged-token>  → flag
 */

const express = require("express");
const jwt     = require("jsonwebtoken");
const fs      = require("fs");
const path    = require("path");

const app    = express();
const SECRET = "s3cr3t_jwt_key_not_used_for_none";
const FLAG   = fs.existsSync("/flag.txt")
    ? fs.readFileSync("/flag.txt", "utf8").trim()
    : "CTF{flag_not_configured}";

app.use(express.json());
app.use(express.urlencoded({ extended: true }));

const USERS = { guest: "guest123" };

// ── HTML helper ──────────────────────────────────────────────────────────────

const page = (title, body) => `<!DOCTYPE html>
<html><head><title>${title}</title>
<style>
  body{font-family:monospace;background:#13111a;color:#e2e2e2;margin:0;padding:32px}
  h1{color:#9b59b6}h2{color:#8e44ad}
  .card{background:#1e1a2e;border:1px solid #3a2d5c;border-radius:6px;padding:20px;margin:16px 0}
  code,pre{background:#0d0b14;padding:4px 8px;border-radius:3px;color:#00d4aa}
  pre{padding:12px;white-space:pre-wrap;word-break:break-all}
  input{background:#0d0b14;border:1px solid #3a2d5c;color:#e2e2e2;padding:8px;border-radius:4px;width:100%;margin:4px 0 12px}
  button{background:#9b59b6;color:#fff;border:none;padding:10px 20px;border-radius:4px;cursor:pointer}
  .flag{border-left:4px solid #27ae60;padding:12px;background:#0a1f0a;color:#2ecc71;font-size:1.1rem}
</style>
</head><body>${body}</body></html>`;

// ── Routes ───────────────────────────────────────────────────────────────────

app.get("/", (req, res) => {
    res.send(page("JWT Auth Demo", `
    <h1>🔑 JWT Auth Demo</h1>
    <div class="card">
      <p>This API uses JWT authentication. Login as a guest, then try to reach <code>/admin</code>.</p>
      <h2>Login</h2>
      <form action="/login" method="POST">
        <label>Username</label><input name="username" value="guest">
        <label>Password</label><input name="password" type="password" value="guest123">
        <button>Get Token</button>
      </form>
    </div>
    <div class="card">
      <h2>API Endpoints</h2>
      <pre>POST /login       {"username","password"} → JWT token
GET  /whoami      Authorization: Bearer &lt;token&gt; → decoded claims
GET  /admin       Authorization: Bearer &lt;token&gt; → flag (admin only)</pre>
    </div>`));
});

app.post("/login", (req, res) => {
    const { username, password } = req.body;
    if (!USERS[username] || USERS[username] !== password) {
        return res.status(401).json({ error: "Invalid credentials" });
    }
    const token = jwt.sign(
        { username, role: "user" },
        SECRET,
        { algorithm: "HS256", expiresIn: "1h" }
    );
    // Return JSON for API use or HTML for browser
    if (req.headers["content-type"]?.includes("application/json")) {
        return res.json({ token });
    }
    res.send(page("Token Issued", `
    <h1>Login Successful</h1>
    <div class="card">
      <p>Your JWT token (HS256, role=user):</p>
      <pre id="tok">${token}</pre>
      <p>Use it as: <code>Authorization: Bearer &lt;token&gt;</code></p>
      <p>Try <a href="/admin">/admin</a> — but you're just a user…</p>
    </div>`));
});

app.get("/whoami", (req, res) => {
    const auth = req.headers.authorization;
    if (!auth?.startsWith("Bearer ")) return res.status(401).json({ error: "No token" });
    try {
        const decoded = verifyToken(auth.slice(7));
        res.json({ claims: decoded });
    } catch (e) {
        res.status(401).json({ error: e.message });
    }
});

app.get("/admin", (req, res) => {
    const auth = req.headers.authorization;
    if (!auth?.startsWith("Bearer ")) {
        return res.status(401).send(page("Unauthorized", `
        <h1>401 Unauthorized</h1>
        <p>Provide a Bearer token in the Authorization header.</p>`));
    }
    let decoded;
    try {
        decoded = verifyToken(auth.slice(7));
    } catch (e) {
        return res.status(401).send(page("Invalid Token", `<h1>401</h1><p>${e.message}</p>`));
    }
    if (decoded.role !== "admin") {
        return res.status(403).send(page("Forbidden", `
        <h1>403 Forbidden</h1>
        <p>Admin access required. Your role: <code>${decoded.role}</code></p>`));
    }
    res.send(page("Admin Panel", `
    <h1>🛡️ Admin Panel</h1>
    <div class="flag">🚩 ${FLAG}</div>
    <div class="card"><p>Welcome, ${decoded.username || "admin"}.</p></div>`));
});

// ── VULNERABLE token verifier ────────────────────────────────────────────────

function verifyToken(token) {
    const parts = token.split(".");
    if (parts.length !== 3) throw new Error("Malformed token");

    // Decode header — pad base64url to base64
    const headerJson = Buffer.from(
        parts[0].replace(/-/g, "+").replace(/_/g, "/") +
        "=".repeat((4 - parts[0].length % 4) % 4),
        "base64"
    ).toString();
    const header = JSON.parse(headerJson);

    if (header.alg === "none") {
        // BUG: accepts unsigned tokens — attacker can forge any payload
        const payloadJson = Buffer.from(
            parts[1].replace(/-/g, "+").replace(/_/g, "/") +
            "=".repeat((4 - parts[1].length % 4) % 4),
            "base64"
        ).toString();
        return JSON.parse(payloadJson);
    }

    // Normal path: verify with secret
    return jwt.verify(token, SECRET);
}

app.listen(3000, "0.0.0.0", () =>
    console.log("jwt-admin listening on :3000"));
