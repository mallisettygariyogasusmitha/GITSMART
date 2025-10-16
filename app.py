# app.py
import os
import io
import zipfile
import base64
import tempfile
import traceback
import requests
from typing import Optional, List, Dict, Any, Tuple

from flask import (
    Flask, render_template, request, redirect, url_for, session,
    jsonify, send_file
)
from werkzeug.utils import secure_filename

from utils.github_api import GitHubAPI

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.getenv("GITSMART_SECRET", "gitsmart-secret-key-change-in-prod")

PISTON_ENDPOINTS = [
    "https://emkc.org/api/v2/piston/execute",
    "https://piston.rs/execute"
]

ALLOWED_UPLOAD_EXT = {
    "py", "js", "ts", "java", "c", "cpp", "go", "rb", "php", "cs",
    "rs", "kt", "swift", "sh", "r", "lua", "hs", "scala", "pl", "dart",
    "html", "css", "json", "md", "txt", "yml", "yaml"
}

def _json_ok(payload: dict = None) -> dict:
    payload = payload or {}
    payload["success"] = True
    return payload

def get_gh() -> Optional[GitHubAPI]:
    pat = session.get("pat")
    if not pat:
        return None
    try:
        return GitHubAPI(pat)
    except Exception:
        traceback.print_exc()
        return None

def detect_language_from_filename(filename: str) -> Optional[str]:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    mapping = {
        "py": "python", "js": "javascript", "ts": "typescript", "java": "java",
        "c": "c", "cpp": "cpp", "go": "go", "rb": "ruby", "php": "php", "cs": "csharp",
        "rs": "rust", "kt": "kotlin", "swift": "swift", "sh": "bash", "r": "r",
        "lua": "lua", "hs": "haskell", "scala": "scala", "pl": "perl", "dart": "dart",
        "m": "objective-c", "html": "html", "css": "css", "jsx": "jsx", "tsx": "tsx",
        "txt": "text", "md": "text", "json": "json", "yml": "yaml", "yaml": "yaml"
    }
    return mapping.get(ext)

@app.route("/", methods=["GET"])
def index():
    if "pat" in session:
        return redirect(url_for("dashboard"))
    return render_template("login.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    pat = (request.form.get("pat") or "").strip()
    if not pat:
        return render_template("login.html", error="Enter your GitHub PAT")
    try:
        gh = GitHubAPI(pat)
        user = gh.get_user()
        if not user or (isinstance(user, dict) and user.get("message")):
            return render_template("login.html", error="Invalid PAT or missing repo scopes")
        session["pat"] = pat
        session["username"] = user.get("login")
        return redirect(url_for("dashboard"))
    except Exception:
        traceback.print_exc()
        return render_template("login.html", error="Unexpected error authenticating token")

@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/dashboard")
def dashboard():
    if "pat" not in session:
        return redirect(url_for("index"))
    return render_template("dashboard.html", username=session.get("username"))

# Public repos
@app.route("/api/public_repos")
def api_public_repos():
    q = request.args.get("q", "stars:>20000")
    per_page = int(request.args.get("per_page", 20) or 20)
    try:
        r = requests.get("https://api.github.com/search/repositories",
                         params={"q": q, "sort": "stars", "order": "desc", "per_page": per_page},
                         timeout=10)
        if r.status_code == 200:
            items = r.json().get("items", [])
            repos = []
            for it in items:
                repos.append({
                    "full_name": it.get("full_name"),
                    "description": it.get("description"),
                    "stargazers_count": it.get("stargazers_count"),
                    "owner": {"login": it.get("owner", {}).get("login")},
                    "name": it.get("name")
                })
            return jsonify(_json_ok({"repos": repos}))
        return jsonify({"success": False, "error": r.text}), 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

# User repos
@app.route("/api/repos")
def api_repos():
    if "pat" not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    gh = get_gh()
    if not gh:
        return jsonify({"success": False, "error": "GitHub client unavailable"}), 500
    try:
        repos = gh.get_repos() or []
        out = []
        for r in repos:
            if isinstance(r, dict):
                out.append({
                    "name": r.get("name"),
                    "full_name": r.get("full_name"),
                    "description": r.get("description"),
                    "private": r.get("private"),
                    "forks_count": r.get("forks_count"),
                    "open_issues_count": r.get("open_issues_count"),
                    "created_at": r.get("created_at"),
                    "updated_at": r.get("updated_at"),
                    "owner": r.get("owner", {})
                })
        return jsonify(_json_ok({"repos": out}))
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

# Create repo
@app.route("/api/create_repo", methods=["POST"])
def api_create_repo():
    if "pat" not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    data = request.json or request.form or {}
    name = (data.get("name") or "").strip()
    description = data.get("description") or "Repository created with GitSmart"
    license_choice = data.get("license") or data.get("repo-license") or "mit"
    private = bool(data.get("private", False))
    if not name:
        return jsonify({"success": False, "error": "name required"}), 400

    gh = get_gh()
    if not gh:
        return jsonify({"success": False, "error": "GitHub client unavailable"}), 500
    try:
        username = session.get("username")
        try:
            info = gh.get_repo_info(username, name)
        except Exception:
            info = None
        if info and not info.get("message"):
            return jsonify({"success": False, "error": f"Repository '{name}' already exists."}), 200
        res = gh.create_repo(username, name, description, license_choice, private)
        if not res or (isinstance(res, dict) and res.get("error")):
            msg = res.get("error") if isinstance(res, dict) else "Failed to create repo"
            return jsonify({"success": False, "error": msg}), 400
        try:
            if not gh.file_exists(username, name, "README.md"):
                gh.ensure_readme(username, name)
            if not gh.file_exists(username, name, "LICENSE"):
                gh.ensure_license(username, name, license_choice)
            workflow_path = ".github/workflows/ci.yml"
            if not gh.file_exists(username, name, workflow_path):
                gh.ensure_cicd(username, name)
        except Exception:
            traceback.print_exc()
        return jsonify(_json_ok({"message": f"Repository {name} created successfully!"}))
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

# Delete repo
@app.route("/api/delete_repo", methods=["POST"])
def api_delete_repo():
    if "pat" not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    data = request.json or request.form or {}
    repo = (data.get("repo") or "").strip()
    if not repo:
        return jsonify({"success": False, "error": "repo required"}), 400
    gh = get_gh()
    if not gh:
        return jsonify({"success": False, "error": "GitHub client unavailable"}), 500
    try:
        result = gh.delete_repo(session.get("username"), repo)
        if isinstance(result, dict) and result.get("error"):
            return jsonify({"success": False, "error": result.get("error")}), 400
        return jsonify(_json_ok({"message": f"Repository {repo} deleted successfully!"}))
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

# Upload files
@app.route("/api/upload_files", methods=["POST"])
def api_upload_files():
    if "pat" not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    owner = session.get("username")
    repo = (request.form.get("repo") or request.form.get("upload-repo") or "").strip()
    if not repo:
        return jsonify({"success": False, "error": "repo required"}), 400
    gh = get_gh()
    if not gh:
        return jsonify({"success": False, "error": "GitHub client unavailable"}), 500
    try:
        files = request.files.getlist("files")
        if not files:
            return jsonify({"success": False, "error": "No files uploaded"}), 400
        upload_list: List[Tuple[str, bytes]] = []
        for f in files:
            filename = secure_filename(f.filename)
            data = f.read()
            if filename.lower().endswith(".zip"):
                extracted = gh.extract_zip(data)
                if extracted:
                    upload_list.extend(extracted)
                else:
                    with tempfile.TemporaryDirectory() as td:
                        zpath = os.path.join(td, "tmp.zip")
                        with open(zpath, "wb") as wf:
                            wf.write(data)
                        with zipfile.ZipFile(zpath, "r") as z:
                            for zi in z.infolist():
                                if zi.is_dir():
                                    continue
                                with z.open(zi) as member:
                                    upload_list.append((zi.filename, member.read()))
            else:
                upload_list.append((filename, data))
        results = None
        try:
            if hasattr(gh, "bulk_upload"):
                results = gh.bulk_upload(owner, repo, upload_list)
        except Exception:
            traceback.print_exc()
            results = None
        if results is None:
            results = []
            for fname, b in upload_list:
                try:
                    res = gh.upload_file(owner, repo, fname, b, f"Upload {fname}")
                    results.append(res)
                except Exception as e:
                    traceback.print_exc()
                    results.append({"error": str(e)})
        return jsonify(_json_ok({"message": "Files uploaded successfully!", "files": results}))
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

# List files
@app.route("/api/list_files")
def api_list_files():
    owner = (request.args.get("owner") or session.get("username"))
    repo = request.args.get("repo", "").strip()
    if not owner or not repo:
        return jsonify({"success": False, "error": "owner and repo required"}), 400
    gh = get_gh() if "pat" in session else None
    try:
        files_resp = None
        if gh:
            try:
                files_resp = gh.list_repo_files(owner, repo)
            except Exception:
                files_resp = None
        candidate_files: List[dict] = []
        if isinstance(files_resp, dict) and files_resp.get("tree"):
            branch = request.args.get("branch") or "main"
            # normalize tree
            for item in files_resp.get("tree", []):
                typ = item.get("type")
                p = item.get("path")
                if not p:
                    continue
                candidate_files.append({
                    "name": p.split("/")[-1],
                    "path": p,
                    "type": "file" if typ == "blob" else "dir",
                    "download_url": f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{p}" if typ == "blob" else None
                })
        elif isinstance(files_resp, list):
            for it in files_resp:
                if isinstance(it, dict):
                    candidate_files.append({
                        "name": it.get("name"),
                        "path": it.get("path"),
                        "type": it.get("type", "file"),
                        "download_url": it.get("download_url")
                    })
        return jsonify(_json_ok({"files": candidate_files}))
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

# Get file content
@app.route("/api/get_file")
def api_get_file():
    owner = (request.args.get("owner") or session.get("username"))
    repo = request.args.get("repo", "").strip()
    path = request.args.get("path", "").strip()
    branch = request.args.get("branch", "").strip() or None
    if not owner or not repo or not path:
        return jsonify({"success": False, "error": "owner, repo, path required"}), 400
    gh = get_gh()
    if not gh:
        return jsonify({"success": False, "error": "GitHub client unavailable"}), 500
    try:
        tried = []
        content = None
        if branch:
            tried.append(branch)
            c = gh.get_file_text(owner, repo, path, ref=branch)
            if isinstance(c, dict) and c.get("error"):
                content = None
            else:
                content = c
        if content is None:
            repo_info = gh.get_repo_info(owner, repo) or {}
            default_branch = repo_info.get("default_branch")
            if default_branch and default_branch not in tried:
                tried.append(default_branch)
                c = gh.get_file_text(owner, repo, path, ref=default_branch)
                if isinstance(c, dict) and c.get("error"):
                    content = None
                else:
                    content = c
        for b in ("main", "master"):
            if content is None and b not in tried:
                tried.append(b)
                c = gh.get_file_text(owner, repo, path, ref=b)
                if isinstance(c, dict) and c.get("error"):
                    content = None
                else:
                    content = c
        if content is None:
            # raw fallback
            for b in tried or ["main"]:
                try:
                    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{b}/{path}"
                    rr = requests.get(raw_url, timeout=8)
                    if rr.status_code == 200:
                        content = rr.text
                        break
                except Exception:
                    continue
        if content is None:
            return jsonify({"success": False, "error": "File not found on branches tried", "tried": tried}), 404
        return jsonify(_json_ok({"path": path, "content": content}))
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

# Delete file
@app.route("/api/delete_file", methods=["POST"])
def api_delete_file():
    if "pat" not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    data = request.json or request.form or {}
    repo = (data.get("repo") or "").strip()
    path = (data.get("path") or "").strip()
    if not repo or not path:
        return jsonify({"success": False, "error": "repo and path required"}), 400
    gh = get_gh()
    if not gh:
        return jsonify({"success": False, "error": "GitHub client unavailable"}), 500
    try:
        owner = session.get("username")
        res = gh.delete_file(owner, repo, path)
        if isinstance(res, dict) and res.get("error"):
            return jsonify({"success": False, "error": res.get("error")}), 400
        return jsonify(_json_ok({"message": f"File {path} deleted from {repo}"}))
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

# Run code via Piston
@app.route("/api/run", methods=["POST"])
def api_run():
    payload = request.json or {}
    owner = payload.get("owner") or session.get("username")
    repo = payload.get("repo", "")
    path = payload.get("path", "")
    stdin = payload.get("stdin", "")
    language = payload.get("language", None)
    if not owner or not repo or not path:
        return jsonify({"success": False, "error": "owner, repo, path required"}), 400
    gh = get_gh()
    if not gh:
        return jsonify({"success": False, "error": "GitHub client unavailable"}), 500
    try:
        file_text = gh.get_file_text(owner, repo, path)
        if isinstance(file_text, dict) and file_text.get("error"):
            return jsonify({"success": False, "error": file_text.get("error")}), 400
        if file_text is None:
            return jsonify({"success": False, "error": "Could not fetch file content"}), 404
        if path.lower().endswith((".html", ".css")):
            return jsonify(_json_ok({"preview": True, "content": file_text, "path": path}))
        if path.lower().endswith((".jsx", ".tsx")):
            return jsonify({"success": False, "error": "React/JSX requires build step; preview HTML instead."}), 400
        if not language:
            language = detect_language_from_filename(path)
        if not language:
            return jsonify({"success": False, "error": "Could not detect language"}), 400
        piston_payload = {
            "language": language,
            "version": "*",
            "files": [{"name": os.path.basename(path), "content": file_text}],
            "stdin": stdin or ""
        }
        for endpoint in PISTON_ENDPOINTS:
            try:
                r = requests.post(endpoint, json=piston_payload, timeout=30)
                if r.status_code == 200:
                    run = r.json().get("run", {}) or r.json()
                    stdout = run.get("stdout", "") or run.get("output", "")
                    stderr = run.get("stderr", "") or run.get("error", "")
                    exit_code = run.get("code", 0) or run.get("exit", 0)
                    return jsonify(_json_ok({
                        "stdout": stdout,
                        "stderr": stderr,
                        "exit_code": exit_code,
                        "language": language,
                        "file": path
                    }))
            except Exception:
                traceback.print_exc()
                continue
        return jsonify({"success": False, "error": "Execution service failed"}), 502
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

# Download repo zip
@app.route("/api/download/<owner>/<repo>")
def api_download(owner, repo):
    branch = request.args.get("branch", "main")
    gh = get_gh()
    try:
        if gh:
            data = gh.download_repo_zip(owner, repo, branch=branch)
            if data:
                return send_file(io.BytesIO(data), as_attachment=True, download_name=f"{repo}-{branch}.zip")
        for b in (branch, "main", "master"):
            url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{b}.zip"
            try:
                head = requests.head(url, timeout=5)
                if head.status_code == 200:
                    return redirect(url)
            except Exception:
                continue
        return jsonify({"success": False, "error": "Could not find branch zip"}), 404
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

# Add CI/CD workflow
@app.route("/api/add_cicd", methods=["POST"])
def api_add_cicd():
    if "pat" not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    data = request.json or {}
    repo = (data.get("repo") or "").strip()
    if not repo:
        return jsonify({"success": False, "error": "repo required"}), 400
    gh = get_gh()
    if not gh:
        return jsonify({"success": False, "error": "GitHub client unavailable"}), 500
    try:
        path = ".github/workflows/ci.yml"
        if gh.file_exists(session.get("username"), repo, path):
            return jsonify(_json_ok({"message": "CI/CD workflow already present"}))
        gh.ensure_cicd(session.get("username"), repo)
        return jsonify(_json_ok({"message": "CI/CD workflow added"}))
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

# Settings & whoami
@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "GET":
        return jsonify(_json_ok({
            "username": session.get("username"),
            "has_pat": "pat" in session
        }))
    data = request.json or {}
    action = data.get("action")
    if action == "logout":
        session.clear()
        return jsonify(_json_ok({"message": "Logged out"}))
    return jsonify({"success": False, "error": "Unknown action"}), 400

@app.route("/api/whoami")
def api_whoami():
    if "pat" not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    return jsonify(_json_ok({"username": session.get("username")}))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
