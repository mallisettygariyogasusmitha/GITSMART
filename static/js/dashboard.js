
// static/js/dashboard.js
window.GitSmart = (function () {
  // Helper: api fetch
  async function apiFetch(url, opts = {}) {
    try {
      const r = await fetch(url, opts);
      const j = await r.json();
      return j;
    } catch (e) {
      console.error("API fetch failed", e);
      return { success: false, error: String(e) };
    }
  }

  // DOM utilities
  function el(id) { return document.getElementById(id); }
  function escapeHtml(s) {
    if (s == null) return "";
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  // UI sections
  function showSection(name) {
    document.querySelectorAll(".section").forEach(s => s.classList.remove("active"));
    const map = { home: "home-section", repos: "repos-section", run: "run-section", settings: "settings-section" };
    const id = map[name] || map.home;
    document.getElementById(id).classList.add("active");
  }

  // Load public repos (Home)
  async function loadPublicRepos() {
    const data = await apiFetch("/api/public_repos");
    const container = el("public-repos");
    if (!container) return;
    container.innerHTML = "";
    if (!data.success) {
      container.innerHTML = "<p>Error loading public repos</p>";
      return;
    }
    data.repos.forEach(r => {
      const card = document.createElement("div");
      card.className = "public-card";
      card.innerHTML = `
        <div class="public-header"><strong>${escapeHtml(r.full_name)}</strong></div>
        <div class="public-desc">${escapeHtml(r.description || "")}</div>
        <div class="public-meta">⭐ ${r.stargazers_count || 0}</div>
        <div class="public-actions">
          <button class="btn-open">Show Files</button>
          <button class="btn-run">Run</button>
          <a class="btn-download" href="/api/download/${encodeURIComponent(r.owner.login)}/${encodeURIComponent(r.name)}" target="_blank">Download</a>
        </div>
      `;
      // handlers
      card.querySelector(".btn-open").addEventListener("click", () => {
        openPublicRepoFiles(r.owner.login, r.name);
      });
      card.querySelector(".btn-run").addEventListener("click", () => {
        runFromPublic(r.owner.login, r.name);
      });
      container.appendChild(card);
    });
  }

  // Load user's repos in sidebar + repos page
  async function loadRepos() {
    const data = await apiFetch("/api/repos");
    const list = el("repo-list");
    const reposContainer = el("repos-container");
    if (list) list.innerHTML = "";
    if (reposContainer) reposContainer.innerHTML = "";
    if (!data.success) {
      if (list) list.innerHTML = "<li>Error</li>";
      if (reposContainer) reposContainer.innerHTML = "<p>Error loading repos</p>";
      return;
    }
    data.repos.forEach(r => {
      // sidebar
      if (list) {
        const li = document.createElement("li");
        li.className = "repo-item";
        li.textContent = r.full_name || r.name;
        li.addEventListener("click", () => openRepo(r));
        list.appendChild(li);
      }
      // main repos area
      if (reposContainer) {
        const card = document.createElement("div");
        card.className = "repo-card";
        card.innerHTML = `
          <h4>${escapeHtml(r.full_name)}</h4>
          <div>Created: ${escapeHtml(r.created_at || "")} | Updated: ${escapeHtml(r.updated_at || "")}</div>
          <div>Forks: ${r.forks_count || 0} | Issues: ${r.open_issues_count || 0} | ${r.private ? "Private" : "Public"}</div>
          <div class="repo-actions">
            <button class="show-files">Show Files</button>
            <button class="run-repo">Run</button>
            <a class="download-repo" href="/api/download/${encodeURIComponent((r.owner||{}).login||"")}/${encodeURIComponent(r.name)}" target="_blank">Download</a>
            <button class="delete-repo">Delete</button>
          </div>
          <div class="repo-files" style="margin-top:8px;"></div>
        `;
        // attach handlers
        card.querySelector(".show-files").addEventListener("click", () => showRepoFiles(r, card.querySelector(".repo-files")));
        card.querySelector(".run-repo").addEventListener("click", () => openRepo(r, true));
        card.querySelector(".delete-repo").addEventListener("click", () => deleteRepo(r.name));
        reposContainer.appendChild(card);
      }
    });
  }

  // Show files for a public repo (open modal-like div)
  async function openPublicRepoFiles(owner, repo) {
    const data = await apiFetch(`/api/list_files?owner=${encodeURIComponent(owner)}&repo=${encodeURIComponent(repo)}`);
    if (!data.success) {
      alert("Failed to load files: " + (data.error || ""));
      return;
    }
    const files = data.files || [];
    const box = document.createElement("div");
    box.className = "modal";
    box.innerHTML = `<div class="modal-inner"><h3>${owner}/${repo} - Files</h3><div class="file-list"></div><div class="modal-close">Close</div></div>`;
    const fl = box.querySelector(".file-list");
    if (!files.length) fl.innerHTML = "<p>No files</p>";
    files.forEach(f => {
      const li = document.createElement("div");
      li.className = "file-row";
      li.innerHTML = `<span>${escapeHtml(f.path)}</span>
        <div class="file-actions">
          <button class="open-file">Open</button>
          <button class="run-file">Run</button>
          <a class="download-file" href="${f.download_url || '#'}" target="_blank">Download</a>
        </div>`;
      li.querySelector(".open-file").addEventListener("click", () => openPublicFile(owner, repo, f.path));
      li.querySelector(".run-file").addEventListener("click", () => runPublic(owner, repo, f.path));
      fl.appendChild(li);
    });
    box.querySelector(".modal-close").addEventListener("click", () => box.remove());
    document.body.appendChild(box);
  }

  async function openPublicFile(owner, repo, path) {
    const data = await apiFetch(`/api/get_file?owner=${encodeURIComponent(owner)}&repo=${encodeURIComponent(repo)}&path=${encodeURIComponent(path)}`);
    if (!data.success) { alert("Failed: " + (data.error||"")); return; }
    // show in modal
    const box = document.createElement("div");
    box.className = "modal";
    box.innerHTML = `<div class="modal-inner"><h3>${escapeHtml(path)}</h3><pre class="file-preview"></pre><div class="modal-close">Close</div></div>`;
    box.querySelector(".file-preview").textContent = data.content || "";
    box.querySelector(".modal-close").addEventListener("click", () => box.remove());
    document.body.appendChild(box);
  }

  async function runPublic(owner, repo, path) {
    // call run endpoint; display output in modal
    const res = await apiFetch("/api/run", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ owner, repo, path })
    });
    const box = document.createElement("div");
    box.className = "modal";
    box.innerHTML = `<div class="modal-inner"><h3>Run: ${escapeHtml(path)}</h3><pre class="run-output"></pre><div class="modal-close">Close</div></div>`;
    const out = box.querySelector(".run-output");
    if (!res.success) out.textContent = "Error: " + (res.error || "");
    else if (res.preview) out.textContent = "Preview (not runnable) — open file to view.";
    else out.textContent = `STDOUT:\n${res.stdout||""}\n\nSTDERR:\n${res.stderr||""}`;
    box.querySelector(".modal-close").addEventListener("click", () => box.remove());
    document.body.appendChild(box);
  }

  // Show repo files in repo card
  async function showRepoFiles(repo, container) {
    container.innerHTML = "<p>Loading files...</p>";
    const owner = (repo.owner || {}).login || sessionStorage.getItem("username") || "";
    const data = await apiFetch(`/api/list_files?owner=${encodeURIComponent(owner)}&repo=${encodeURIComponent(repo.name)}`);
    if (!data.success) { container.innerHTML = "<p>Failed to load files</p>"; return; }
    const files = data.files || [];
    if (!files.length) { container.innerHTML = "<p>No files</p>"; return; }
    container.innerHTML = "";
    files.forEach(f => {
      const row = document.createElement("div");
      row.className = "file-row";
      row.innerHTML = `<span>${escapeHtml(f.path)}</span>
        <div class="file-actions">
          <button class="open">Open</button>
          <button class="run">Run</button>
          <a class="download" href="${f.download_url || '#'}" target="_blank">Download</a>
        </div>`;
      row.querySelector(".open").addEventListener("click", () => openRepoFile(repo, f.path));
      row.querySelector(".run").addEventListener("click", () => runRepoFile(repo, f.path));
      container.appendChild(row);
    });
  }

  async function openRepoFile(repo, path) {
    const owner = (repo.owner || {}).login || sessionStorage.getItem("username") || "";
    const data = await apiFetch(`/api/get_file?owner=${encodeURIComponent(owner)}&repo=${encodeURIComponent(repo.name)}&path=${encodeURIComponent(path)}`);
    if (!data.success) { alert("Failed: " + (data.error || "")); return; }
    const modal = document.createElement("div");
    modal.className = "modal";
    modal.innerHTML = `<div class="modal-inner"><h3>${escapeHtml(path)}</h3><pre class="file-preview"></pre><div class="modal-close">Close</div></div>`;
    modal.querySelector(".file-preview").textContent = data.content || "";
    modal.querySelector(".modal-close").addEventListener("click", () => modal.remove());
    document.body.appendChild(modal);
  }

  async function runRepoFile(repo, path) {
    const owner = (repo.owner || {}).login || sessionStorage.getItem("username") || "";
    const res = await apiFetch("/api/run", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ owner, repo: repo.name, path })
    });
    const modal = document.createElement("div");
    modal.className = "modal";
    modal.innerHTML = `<div class="modal-inner"><h3>Run Result</h3><pre class="run-output"></pre><div class="modal-close">Close</div></div>`;
    const out = modal.querySelector(".run-output");
    if (!res.success) out.textContent = "Error: " + (res.error || "");
    else if (res.preview) out.textContent = "Preview (non-executable content).";
    else out.textContent = `STDOUT:\n${res.stdout||""}\n\nSTDERR:\n${res.stderr||""}`;
    modal.querySelector(".modal-close").addEventListener("click", () => modal.remove());
    document.body.appendChild(modal);
  }

  // Provide Run tab file selector + run selected
  async function populateRunSelectorForRepo(owner, repoName) {
    const sel = el("file-selector");
    if (!sel) return;
    sel.innerHTML = "";
    const data = await apiFetch(`/api/list_files?owner=${encodeURIComponent(owner)}&repo=${encodeURIComponent(repoName)}`);
    if (!data.success) return;
    (data.files || []).forEach(f => {
      const opt = document.createElement("option");
      opt.value = JSON.stringify({ owner, repo: repoName, path: f.path });
      opt.textContent = f.path;
      sel.appendChild(opt);
    });
  }

  // Create repo (UI modal)
  async function createRepo() {
    const name = prompt("Repository name?");
    if (!name) return;
    const res = await apiFetch("/api/create_repo", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ name })
    });
    if (!res.success) alert("Create failed: " + (res.error||""));
    else {
      await loadRepos();
      showSection("repos");
    }
  }

  async function deleteRepo(repoName) {
    if (!confirm(`Delete repo ${repoName}?`)) return;
    const res = await apiFetch("/api/delete_repo", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ repo: repoName })
    });
    if (!res.success) alert("Delete failed: " + (res.error||""));
    else {
      await loadRepos();
      showSection("repos");
    }
  }

  // Upload files via selected file input on current repo card
  async function uploadFiles(repoName) {
    // find file input element in DOM - easiest approach: prompt user to choose file(s)
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.onchange = async () => {
      if (!input.files.length) return;
      const fd = new FormData();
      fd.append("repo", repoName);
      Array.from(input.files).forEach(f => fd.append("files", f));
      const r = await fetch("/api/upload_files", { method: "POST", body: fd });
      const j = await r.json();
      if (!j.success) alert("Upload failed: " + (j.error||""));
      else {
        await loadRepos();
        showSection("repos");
      }
    };
    input.click();
  }

  async function deleteFile(repoName, path) {
    if (!confirm(`Delete ${path} from ${repoName}?`)) return;
    const res = await apiFetch("/api/delete_file", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ repo: repoName, path })
    });
    if (!res.success) alert("Delete failed: " + (res.error||""));
    else alert(res.message || "Deleted");
  }

  // Settings: whoami
  async function whoami() {
    const res = await apiFetch("/api/whoami");
    const p = el("profile");
    if (!p) return;
    if (!res.success) p.innerHTML = "<p>Not authenticated</p>";
    else p.innerHTML = `<p>Username: <strong>${escapeHtml(res.username)}</strong></p>`;
  }

  // Init event wiring
  function setupEventHandlers() {
    // nav links
    document.getElementById("nav-home").addEventListener("click", e => { e.preventDefault(); showSection("home"); });
    document.getElementById("nav-repos").addEventListener("click", e => { e.preventDefault(); showSection("repos"); });
    document.getElementById("nav-run").addEventListener("click", e => { e.preventDefault(); showSection("run"); });
    document.getElementById("nav-settings").addEventListener("click", e => { e.preventDefault(); showSection("settings"); whoami(); });

    // create repo button
    const createBtn = document.getElementById("create-repo-btn");
    if (createBtn) createBtn.addEventListener("click", createRepo);

    // logout
    const logoutBtn = document.getElementById("logout-btn");
    if (logoutBtn) logoutBtn.addEventListener("click", async () => {
      const res = await apiFetch("/api/settings", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ action: "logout" })
      });
      if (res.success) window.location.href = "/";
    });

    // run selected file
    const runSelBtn = document.getElementById("run-selected-btn");
    if (runSelBtn) runSelBtn.addEventListener("click", async () => {
      const sel = el("file-selector");
      if (!sel || !sel.value) { alert("Select a file"); return; }
      const obj = JSON.parse(sel.value);
      const res = await apiFetch("/api/run", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ owner: obj.owner, repo: obj.repo, path: obj.path })
      });
      const out = el("run-output");
      if (!res.success) out.innerHTML = `<pre>Error: ${escapeHtml(res.error || "")}</pre>`;
      else if (res.preview) out.innerHTML = `<iframe srcdoc="${escapeHtml(res.content)}" style="width:100%;height:400px"></iframe>`;
      else out.innerHTML = `<pre>STDOUT:\n${escapeHtml(res.stdout||"")}\n\nSTDERR:\n${escapeHtml(res.stderr||"")}</pre>`;
    });
  }

  // initial load
  async function init() {
    setupEventHandlers();
    await loadPublicRepos();
    await loadRepos();
  }

  // Expose
  return {
    init,
    loadRepos,
    loadPublicRepos,
    createRepo,
    deleteRepo,
    addCICD: async function(repoName){ await fetch("/api/add_cicd", { method:"POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({repo:repoName})}); alert("Requested CI/CD add (check repo)."); },
    openRepo: function(r){ openRepo(r); },
    uploadFiles,
    deleteFile,
    runFile: function(repo, path){ runRepoFile(repo, path); },
    whoami
  };
})();

// Start
document.addEventListener("DOMContentLoaded", () => {
  if (window.GitSmart && typeof window.GitSmart.init === "function") {
    window.GitSmart.init();
  }
});
