"""
SSTI (Server-Side Template Injection) challenge.

The "smart notes" app renders user-provided Jinja2 templates.
The flag is injected into the Flask app config as an environment variable
by the Kubernetes scenario — test that env vars survive the pod lifecycle.

Exploit: POST /render with template={{ config.FLAG }}
"""
import os
from flask import Flask, request, render_template_string

app = Flask(__name__)
# FLAG is injected at pod creation time by the Pulumi scenario (K8s env var)
app.config["FLAG"] = os.environ.get("FLAG", "CTF{flag_not_configured_check_scenario}")

STYLE = """
<style>
  * { box-sizing: border-box; }
  body { font-family: monospace; background: #0f0e17; color: #fffffe; margin: 0; padding: 0; }
  header { background: #ff8906; padding: 16px 32px; }
  header h1 { margin: 0; color: #0f0e17; font-size: 1.5rem; }
  main { max-width: 800px; margin: 40px auto; padding: 0 20px; }
  h2 { color: #ff8906; }
  textarea { width: 100%; height: 120px; background: #1a1a2a; border: 1px solid #444; color: #fffffe;
             padding: 12px; border-radius: 4px; font-family: monospace; font-size: 0.9rem; }
  button { background: #ff8906; color: #0f0e17; border: none; padding: 10px 24px;
           border-radius: 4px; cursor: pointer; font-weight: bold; margin-top: 8px; }
  .output { background: #1a1a2a; border-left: 4px solid #ff8906; padding: 16px;
            margin-top: 20px; white-space: pre-wrap; border-radius: 0 4px 4px 0; }
  .error { border-left-color: #f25f4c; color: #f25f4c; }
  code { background: #1a1a2a; padding: 2px 6px; border-radius: 3px; }
  .examples { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 12px; }
  .ex { background: #1a1a2a; padding: 8px 12px; border-radius: 4px; font-size: 0.85rem; }
</style>
"""


@app.route("/", methods=["GET", "POST"])
def render_view():
    output = ""
    error = ""
    template = request.form.get("template", "")

    if request.method == "POST" and template:
        try:
            output = render_template_string(template)
        except Exception as e:
            error = str(e)

    output_html = ""
    if output:
        output_html = f'<div class="output">{output}</div>'
    elif error:
        output_html = f'<div class="output error">Error: {error}</div>'

    return f"""<!DOCTYPE html>
<html><head><title>Smart Notes</title>{STYLE}</head>
<body>
<header><h1>📝 Smart Notes — Jinja2 Template Renderer</h1></header>
<main>
  <p>Render Jinja2 templates live. Supports all standard expressions and filters.</p>
  <form method="POST">
    <textarea name="template" placeholder="{{{{ 2 + 2 }}}}">{template}</textarea><br>
    <button>▶ Render</button>
  </form>
  {output_html}
  <h2>Examples</h2>
  <div class="examples">
    <div class="ex"><code>{{{{ 7 * 7 }}}}</code> → 49</div>
    <div class="ex"><code>{{{{ "hello" | upper }}}}</code> → HELLO</div>
    <div class="ex"><code>{{{{ range(5) | list }}}}</code> → [0,1,2,3,4]</div>
    <div class="ex"><code>{{{{ config }}}}</code> → app config dict</div>
  </div>
</main>
</body></html>"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
