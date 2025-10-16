# utils/github_api.py
import os
import requests
import base64
import zipfile
import io
from typing import List, Tuple, Optional, Dict

GITHUB_API = "https://api.github.com"

class GitHubAPI:
    """
    Minimal GitHub helper that uses a personal access token (PAT).
    Methods implemented to match app.py expectations.
    """

    def __init__(self, token: str):
        if not token:
            raise ValueError("token required")
        self.token = token
        self.headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json"
        }

    # -------------- User & repos --------------
    def get_user(self) -> Dict:
        r = requests.get(f"{GITHUB_API}/user", headers=self.headers, timeout=10)
        try:
            return r.json()
        except Exception:
            return {"message": "failed"}

    def get_repos(self) -> List[Dict]:
        # list user's repos (paginated). fetch first 100 for simplicity
        repos = []
        page = 1
        while True:
            r = requests.get(f"{GITHUB_API}/user/repos", headers=self.headers,
                             params={"per_page": 100, "page": page}, timeout=10)
            if r.status_code != 200:
                break
            batch = r.json()
            if not isinstance(batch, list) or len(batch) == 0:
                break
            repos.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return repos

    def get_repo_info(self, owner: str, repo: str) -> Dict:
        r = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}", headers=self.headers, timeout=10)
        return r.json() if r.status_code in (200, 201) else {"message": r.text}

    def create_repo(self, owner_or_user: str, name: str, description: str = "", license: str = "mit", private: bool = False):
        # create under authenticated user only (owner_or_user not used for org creation)
        payload = {"name": name, "description": description, "private": bool(private), "auto_init": True}
        r = requests.post(f"{GITHUB_API}/user/repos", headers=self.headers, json=payload, timeout=15)
        if r.status_code in (200, 201):
            return r.json()
        return {"error": r.json().get("message", r.text)}

    def delete_repo(self, owner: str, repo: str):
        r = requests.delete(f"{GITHUB_API}/repos/{owner}/{repo}", headers=self.headers, timeout=10)
        if r.status_code in (204,):
            return {"ok": True}
        try:
            return {"error": r.json().get("message", r.text)}
        except Exception:
            return {"error": r.text}

    # -------------- Listing files --------------
    def list_repo_files(self, owner: str, repo: str):
        """
        Tries to use git/trees recursive to list repository files.
        Falls back to contents root listing when necessary.
        Returns either dict (tree) or list of items.
        """
        # get default branch first
        ri = self.get_repo_info(owner, repo)
        default_branch = ri.get("default_branch", "main")
        try:
            r = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1",
                             headers=self.headers, timeout=15)
            if r.status_code == 200:
                return r.json()  # contains "tree" list
        except Exception:
            pass

        # fallback: list root contents (non-recursive)
        try:
            r2 = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}/contents", headers=self.headers, timeout=10)
            if r2.status_code == 200:
                return r2.json()  # list
        except Exception:
            pass

        return []

    # -------------- File content --------------
    def get_file_text(self, owner: str, repo: str, path: str, ref: Optional[str] = None) -> Optional[str]:
        params = {}
        if ref:
            params["ref"] = ref
        r = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}", headers=self.headers, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get("encoding") == "base64" and data.get("content") is not None:
                try:
                    return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
                except Exception:
                    return data.get("content")
            # sometimes GitHub returns raw text for certain endpoints
            return data.get("content")
        # not found -> return None or error dict
        try:
            return {"error": r.json().get("message", r.text)}
        except Exception:
            return None

    def file_exists(self, owner: str, repo: str, path: str, ref: Optional[str] = None) -> bool:
        params = {}
        if ref:
            params["ref"] = ref
        r = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}", headers=self.headers, params=params, timeout=8)
        return r.status_code == 200

    # -------------- Upload & delete --------------
    def upload_file(self, owner: str, repo: str, path: str, content_bytes: bytes, message: str = "Upload via GitSmart"):
        """
        Create or update a file. Returns JSON response or error dict.
        """
        try:
            # check if exists to supply sha
            r_get = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}", headers=self.headers, timeout=8)
            sha = None
            if r_get.status_code == 200:
                sha = r_get.json().get("sha")
        except Exception:
            sha = None

        payload = {
            "message": message,
            "content": base64.b64encode(content_bytes).decode("utf-8")
        }
        if sha:
            payload["sha"] = sha

        r = requests.put(f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}", headers=self.headers, json=payload, timeout=20)
        if r.status_code in (200, 201):
            return r.json()
        try:
            return {"error": r.json().get("message", r.text)}
        except Exception:
            return {"error": r.text}

    def delete_file(self, owner: str, repo: str, path: str, message: str = "Delete via GitSmart"):
        # need sha
        r_get = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}", headers=self.headers, timeout=8)
        if r_get.status_code != 200:
            return {"error": "File not found"}
        sha = r_get.json().get("sha")
        payload = {"message": message, "sha": sha}
        r = requests.delete(f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}", headers=self.headers, json=payload, timeout=15)
        if r.status_code in (200, 204):
            # delete returns 200 with content info
            try:
                return r.json()
            except Exception:
                return {"ok": True}
        try:
            return {"error": r.json().get("message", r.text)}
        except Exception:
            return {"error": r.text}

    # -------------- Bulk upload & zip --------------
    def bulk_upload(self, owner: str, repo: str, items: List[Tuple[str, bytes]]):
        results = []
        for path, b in items:
            res = self.upload_file(owner, repo, path, b, message=f"Upload {path}")
            results.append(res)
        return results

    def extract_zip(self, raw_bytes: bytes) -> Optional[List[Tuple[str, bytes]]]:
        try:
            out = []
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as z:
                for zi in z.infolist():
                    if zi.is_dir():
                        continue
                    with z.open(zi) as fh:
                        out.append((zi.filename, fh.read()))
            return out
        except Exception:
            return None

    # -------------- Helpers to ensure files --------------
    def ensure_readme(self, owner: str, repo: str):
        content = f"# {repo}\n\nCreated with GitSmart.\n"
        return self.upload_file(owner, repo, "README.md", content.encode("utf-8"), "Add README")

    def ensure_license(self, owner: str, repo: str, license_name: str = "mit"):
        # Add a minimal MIT license text
        mit = """MIT License

Copyright (c) {year} {owner}

Permission is hereby granted, free of charge, to any person obtaining a copy
...
""".format(year="2024", owner=owner)
        return self.upload_file(owner, repo, "LICENSE", mit.encode("utf-8"), "Add LICENSE")

    def ensure_cicd(self, owner: str, repo: str):
        workflow = """name: CI

on:
  push:
    branches: [ main ]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run tests
        run: echo "No tests configured"
"""
        path = ".github/workflows/ci.yml"
        return self.upload_file(owner, repo, path, workflow.encode("utf-8"), "Add CI workflow")

    # -------------- Download repo zip --------------
    def download_repo_zip(self, owner: str, repo: str, branch: str = "main") -> Optional[bytes]:
        # GitHub archive link (requires auth when repo private)
        url = f"https://api.github.com/repos/{owner}/{repo}/zipball/{branch}"
        r = requests.get(url, headers=self.headers, timeout=30)
        if r.status_code == 200:
            return r.content
        return None
