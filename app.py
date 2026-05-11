"""Flask MVP for the SwingLogger pitch-and-putt tracker.

Routes:
    GET  /                  upload form (FIT + course)
    POST /upload            run pipeline, redirect to viewer
    GET  /view/<id>         overlay viewer (with inline reclassify panel)
    POST /reclassify/<id>   {marker, class} -> persist + rerun pipeline
"""
import json
import uuid
import subprocess
from pathlib import Path

from flask import (Flask, render_template, request, redirect, url_for,
                   abort, send_file, jsonify, Response)


PROJECT_ROOT = Path(__file__).resolve().parent
RUNS_DIR = PROJECT_ROOT / "web_runs"
RUNS_DIR.mkdir(exist_ok=True)


def discover_courses():
    courses = []
    for f in sorted(PROJECT_ROOT.glob("*.json")):
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict) and "holes" in data and "name" in data:
            courses.append({"file": f.name, "name": data["name"], "n_holes": len(data["holes"])})
    return courses


def regenerate_overlay(run_dir: Path) -> tuple[bool, str]:
    """Run the round_to_geojson + build_round_viewer pipeline for a run dir.
    Reads round.fit, course (from meta.json), and corrections.json if present.
    Returns (success, error_text)."""
    meta = json.loads((run_dir / "meta.json").read_text())
    course_file = PROJECT_ROOT / meta["course"]
    fit_path = run_dir / "round.fit"
    overlay_geojson = run_dir / "overlay.geojson"
    overlay_html = run_dir / "overlay.html"
    corrections_path = run_dir / "corrections.json"

    cmd1 = ["python", str(PROJECT_ROOT / "round_to_geojson.py"),
            str(fit_path), str(course_file),
            "--output", str(overlay_geojson)]
    if corrections_path.exists():
        cmd1 += ["--corrections", str(corrections_path)]
    cmd2 = ["python", str(PROJECT_ROOT / "build_round_viewer.py"),
            str(overlay_geojson),
            "--output", str(overlay_html)]

    for cmd in (cmd1, cmd2):
        result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        if result.returncode != 0:
            return False, f"CMD {cmd[1].split('/')[-1]} failed:\n{result.stderr}"
    return True, ""


# Injected into the viewer HTML so the user can fix misclassifications.
RECLASSIFY_PANEL = """
<style>
  #reclassify-panel {
    position: absolute; top: 80px; right: 14px; z-index: 1000;
    background: white; padding: 10px 12px; border-radius: 8px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.25); font-size: 13px;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    width: 200px; color: #1d3557;
  }
  #reclassify-panel h3 { margin: 0 0 8px; font-size: 13px; color: #1d3557; }
  #reclassify-panel label { display: block; font-size: 11px; font-weight: 600; margin: 6px 0 2px; }
  #reclassify-panel input, #reclassify-panel select {
    width: 100%; padding: 5px 6px; font-size: 13px;
    border: 1px solid #d6dde4; border-radius: 4px;
  }
  #reclassify-panel button {
    width: 100%; padding: 7px; margin-top: 8px;
    background: #2a9d8f; color: white; border: 0; border-radius: 4px;
    font-weight: 600; cursor: pointer; font-size: 13px;
  }
  #reclassify-panel button:disabled { background: #a8dadc; cursor: not-allowed; }
  #reclassify-panel .status { margin-top: 6px; font-size: 11px; color: #2a9d8f; min-height: 14px; }
  #reclassify-panel .status.error { color: #e63946; }
  #reclassify-panel .hint { font-size: 10px; color: #6c8aa3; margin-top: 4px; line-height: 1.4; }
  @media (max-width: 600px) {
    #reclassify-panel { top: auto; bottom: 14px; right: 14px; width: calc(100vw - 28px); max-width: 240px; }
  }
</style>
<div id="reclassify-panel">
  <h3>Reclassify shot</h3>
  <label>Marker #</label>
  <input type="number" id="rc-marker" min="1" max="100" placeholder="from popup">
  <label>Class</label>
  <select id="rc-class">
    <option value="putt">Putt</option>
    <option value="chip">Chip</option>
    <option value="pitch">Pitch</option>
  </select>
  <button id="rc-save">Save & re-render</button>
  <div class="status" id="rc-status"></div>
  <div class="hint">Click any shot marker on the map; the popup shows the marker number.</div>
</div>
<script>
(function() {
  const RUN_ID = '__RUN_ID__';
  const btn = document.getElementById('rc-save');
  const status = document.getElementById('rc-status');
  btn.addEventListener('click', async () => {
    const marker = parseInt(document.getElementById('rc-marker').value, 10);
    const cls = document.getElementById('rc-class').value;
    if (Number.isNaN(marker)) { status.textContent = 'Enter a marker number.'; status.classList.add('error'); return; }
    btn.disabled = true; status.classList.remove('error'); status.textContent = 'Saving…';
    try {
      const r = await fetch('/reclassify/' + RUN_ID, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({marker, class: cls})
      });
      if (!r.ok) {
        const t = await r.text();
        status.textContent = 'Error: ' + t.slice(0, 100);
        status.classList.add('error');
        btn.disabled = false;
        return;
      }
      status.textContent = 'Saved. Reloading…';
      window.location.reload();
    } catch (e) {
      status.textContent = 'Network error.'; status.classList.add('error');
      btn.disabled = false;
    }
  });
})();
</script>
"""


app = Flask(__name__, template_folder=str(PROJECT_ROOT / "templates"))
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024


@app.route("/")
def index():
    return render_template("upload.html", courses=discover_courses())


@app.route("/upload", methods=["POST"])
def upload():
    fit = request.files.get("fit")
    course_file = request.form.get("course")
    if not fit or not fit.filename.lower().endswith(".fit"):
        return "Please upload a .fit file.", 400
    if not course_file or not (PROJECT_ROOT / course_file).exists():
        return "Please pick a valid course.", 400

    run_id = uuid.uuid4().hex[:10]
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True)
    fit.save(str(run_dir / "round.fit"))
    (run_dir / "meta.json").write_text(json.dumps({
        "course": course_file,
        "original_fit": fit.filename,
    }))

    ok, err = regenerate_overlay(run_dir)
    if not ok:
        (run_dir / "error.log").write_text(err)
        return f"Processing failed.<br><pre>{err[-2000:]}</pre>", 500

    return redirect(url_for("view", run_id=run_id))


@app.route("/view/<run_id>")
def view(run_id):
    run_dir = RUNS_DIR / run_id
    overlay_html = run_dir / "overlay.html"
    if not overlay_html.exists():
        abort(404)
    html = overlay_html.read_text()
    panel = RECLASSIFY_PANEL.replace("__RUN_ID__", run_id)
    if "</body>" in html:
        html = html.replace("</body>", panel + "</body>")
    else:
        html += panel
    return Response(html, mimetype="text/html")


@app.route("/reclassify/<run_id>", methods=["POST"])
def reclassify(run_id):
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        abort(404)
    body = request.get_json(silent=True) or {}
    try:
        marker = int(body["marker"])
        cls = body["class"]
    except (KeyError, ValueError, TypeError):
        return "Invalid payload.", 400
    if cls not in ("pitch", "chip", "putt"):
        return "class must be pitch|chip|putt.", 400

    corrections_path = run_dir / "corrections.json"
    corrections = {}
    if corrections_path.exists():
        corrections = json.loads(corrections_path.read_text())
    reclass = corrections.setdefault("reclassify", [])
    # Replace any existing entry for this marker
    reclass[:] = [r for r in reclass if r.get("marker") != marker]
    reclass.append({"marker": marker, "class": cls})
    corrections_path.write_text(json.dumps(corrections, indent=2))

    ok, err = regenerate_overlay(run_dir)
    if not ok:
        return err, 500
    return jsonify({"ok": True, "marker": marker, "class": cls})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
