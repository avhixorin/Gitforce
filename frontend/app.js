/* Gitforce SPA — section 5 frontend requirements.
 * Routes: #/create, #/tasks, #/tasks/:id, #/metrics
 * Uses existing REST + WebSocket endpoints. Vanilla JS, no build step.
 */
(() => {
  "use strict";

  const $app = document.getElementById("app");
  let ws = null;
  let currentTaskId = null;

  // ---- tiny helpers -------------------------------------------------------
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function setActiveNav(route) {
    document.querySelectorAll("nav a").forEach((a) => {
      a.classList.toggle("active", a.dataset.route === route);
    });
  }

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    return res.json();
  }

  function stageList(state = {}) {
    // Ordered workflow stages mapped to state keys/events (section 5.2).
    const stages = [
      { key: "repository", label: "Repository Analysis", get: (s) => !!s.repository_analysis },
      { key: "requirements", label: "Requirements", get: (s) => !!s.requirements },
      { key: "planner", label: "Planning", get: (s) => !!s.plan },
      { key: "coder", label: "Implementation", get: (s) => !!s.implementation },
      { key: "tester", label: "Testing", get: (s) => !!s.test_results },
      { key: "security", label: "Security", get: (s) => !!s.security_results },
      { key: "reviewer", label: "Review", get: (s) => !!s.review_results },
      { key: "judge", label: "Judge", get: (s) => !!s.judge_results },
      { key: "delivery", label: "PR Delivery", get: (s) => !!s.pr },
    ];
    const status = state.status;
    const failed = status === "failed" || status === "cancelled";
    let seenIncomplete = false;
    return stages.map((st) => {
      const done = st.get(state);
      let cls = "pending";
      if (done) cls = "done";
      else if (!seenIncomplete && !failed) { cls = "active"; seenIncomplete = true; }
      else if (failed && !done) cls = "failed";
      if (!done) seenIncomplete = seenIncomplete || true;
      return { ...st, cls };
    });
  }

  // ---- WebSocket live updates (section 5.3) --------------------------------
  function connectWs(taskId) {
    if (ws) { ws.close(); ws = null; }
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws/tasks/${taskId}`);
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      // Re-fetch task state on each event so the dashboard stays fresh.
      renderTask(taskId);
      appendEvent(msg);
    };
  }

  function appendEvent(msg) {
    const box = document.getElementById("event-log");
    if (!box) return;
    const div = document.createElement("div");
    div.innerHTML = `<span class="ts">${esc(new Date(msg.timestamp).toLocaleTimeString())}</span>${esc(msg.event)}`;
    box.prepend(div);
    while (box.children.length > 300) box.lastChild.remove();
  }

  // ---- Routes ---------------------------------------------------------------
  const routes = {
    create: renderCreate,
    tasks: renderTasks,
    metrics: renderMetrics,
  };

  function resolveHash() {
    const hash = location.hash || "#/create";
    const parts = hash.replace(/^#\//, "").split("/");
    const route = parts[0] || "create";
    if (route === "tasks" && parts[1]) return { route: "task", id: parts[1] };
    return { route: routes[route] ? route : "create" };
  }

  async function render() {
    const { route, id } = resolveHash();
    if (route === "task") { setActiveNav("tasks"); return renderTask(id); }
    setActiveNav(route);
    await routes[route]();
  }

  // ---- 5.1 Task creation ----------------------------------------------------
  function renderCreate() {
    $app.innerHTML = `
      <div class="panel">
        <h2>Start a Task</h2>
        <p class="sub" style="color:var(--muted);margin-top:0">
          Provide a GitHub repository and issue, then Gitforce runs the engineering
          workflow and opens a pull request.
        </p>
        <div id="create-error" class="error-box" style="display:none"></div>
        <form id="create-form">
          <div class="form-row">
            <label for="repo">GitHub repository URL *</label>
            <input id="repo" name="repository_url" type="url" required
              placeholder="https://github.com/org/repo" />
          </div>
          <div class="form-row">
            <label for="issue">GitHub issue URL *</label>
            <input id="issue" name="issue_url" type="url" required
              placeholder="https://github.com/org/repo/issues/123" />
          </div>
          <div class="form-grid">
            <div class="form-row">
              <label for="branch">Target branch</label>
              <input id="branch" name="target_branch" placeholder="main" />
            </div>
            <div class="form-row">
              <label for="model">Model</label>
              <input id="model" name="model" placeholder="gpt-4o" />
            </div>
            <div class="form-row">
              <label for="iterations">Max iterations</label>
              <input id="iterations" name="max_iterations" type="number" min="1" max="100" />
            </div>
            <div class="form-row">
              <label for="test_mode">Test execution mode</label>
              <select id="test_mode" name="test_execution_mode">
                <option value="">default</option>
                <option value="sandbox">sandbox</option>
                <option value="skip">skip</option>
              </select>
            </div>
            <div class="form-row">
              <label for="approval_mode">Approval mode</label>
              <select id="approval_mode" name="approval_mode">
                <option value="">auto</option>
                <option value="manual">manual</option>
              </select>
            </div>
          </div>
          <button type="submit" class="btn" id="start-btn">Start Task</button>
        </form>
      </div>`;

    const form = document.getElementById("create-form");
    const errBox = document.getElementById("create-error");
    const btn = document.getElementById("start-btn");

    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      errBox.style.display = "none";
      btn.disabled = true;
      btn.textContent = "Starting…";
      const payload = {};
      for (const el of form.elements) {
        if (el.name && el.value.trim() !== "") {
          payload[el.name] = el.type === "number" ? Number(el.value) : el.value.trim();
        }
      }
      try {
        const result = await api("/api/tasks", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        location.hash = `#/tasks/${result.task_id}`;
      } catch (err) {
        errBox.textContent = err.message;
        errBox.style.display = "block";
        btn.disabled = false;
        btn.textContent = "Start Task";
      }
    });
  }

  // ---- 5.2 / 5.3 Progress dashboard -----------------------------------------
  async function renderTask(id) {
    currentTaskId = id;
    let task;
    try {
      task = await api(`/api/tasks/${id}`);
    } catch (err) {
      $app.innerHTML = `<div class="error-box">${esc(err.message)}</div>`;
      return;
    }

    const stages = stageList(task.state || {});
    const statusBadge = `<span class="badge ${esc(task.status)}">${esc(task.status)}</span>`;
    const elapsed = task.started_at
      ? (Date.now() - new Date(task.started_at).getTime()) / 1000 : 0;

    $app.innerHTML = `
      <div class="panel">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <h2>Task #${esc(task.id.slice(0, 8))} ${statusBadge}</h2>
          <a class="link" href="#/tasks">← All tasks</a>
        </div>
        <dl class="kv" style="margin-top:12px">
          <dt>Repository</dt><dd class="mono">${esc(task.repository_url)}</dd>
          <dt>Issue</dt><dd class="mono">${esc(task.issue_url)}</dd>
          <dt>Elapsed</dt><dd>${formatDuration(elapsed)}</dd>
          ${task.error ? `<dt>Error</dt><dd style="color:var(--err)">${esc(task.error)}</dd>` : ""}
        </dl>
      </div>

      <div class="grid">
        <div class="stat"><div class="label">Status</div><div class="value">${esc(task.status)}</div></div>
        <div class="stat"><div class="label">Iteration</div><div class="value">${esc(task.iteration ?? 0)}</div></div>
        <div class="stat"><div class="label">Retries</div><div class="value">${esc(task.retry_count ?? 0)}</div></div>
        <div class="stat"><div class="label">Elapsed</div><div class="value">${formatDuration(elapsed)}</div></div>
      </div>

      <div class="panel">
        <h3>Workflow Progress</h3>
        <ul class="stages">
          ${stages.map((s) =>
            `<li class="stage ${s.cls}"><span class="dot"></span><span class="name">${esc(s.label)}</span></li>`
          ).join("")}
        </ul>
      </div>

      <div class="panel">
        <h3>Live Events</h3>
        <div class="events" id="event-log"><div>Connected — waiting for events…</div></div>
      </div>

      ${renderResults(task)}
    `;

    connectWs(id);
  }

  // ---- 5.4 Final result ------------------------------------------------------
  function renderResults(task) {
    if (task.status !== "completed") return "";
    const s = task.state || {};
    const pr = task.pr || {};
    const report = task.report || {};
    const judge = s.judge_results || {};
    const sec = s.security_results || {};
    const test = s.test_results || {};

    return `
      <div class="panel">
        <h2>Final Result</h2>
        ${pr.html_url || pr.number
          ? `<p><a class="link" href="${esc(pr.html_url || "#")}" target="_blank">Open Pull Request #${esc(pr.number)}</a>
             — ${esc(pr.title || "")}</p>`
          : `<p style="color:var(--muted)">No PR was opened for this task.</p>`}

        <h3>Summary</h3>
        <pre class="mono" style="white-space:pre-wrap;background:var(--bg-2);padding:12px;border-radius:8px">${esc(report.summary || report.body || "No summary")}</pre>
      </div>

      <div class="grid">
        <div class="stat"><div class="label">Tests Passed</div><div class="value">${esc(test.tests_passed ?? 0)}/${esc(test.tests_run ?? 0)}</div></div>
        <div class="stat"><div class="label">Security</div><div class="value">${esc(sec.passed ? "Passed" : (sec.passed === false ? "Failed" : "—"))}</div></div>
        <div class="stat"><div class="label">Judge Score</div><div class="value">${formatScore(judge.overall_score)}</div></div>
        <div class="stat"><div class="label">Review Approved</div><div class="value">${esc(judge.ready ? "Yes" : "No")}</div></div>
      </div>

      <div class="panel">
        <h3>Evaluation Scores</h3>
        ${scoreBar("Correctness", judge.correctness_score)}
        ${scoreBar("Quality", judge.quality_score)}
        ${scoreBar("Security", judge.security_score)}
        ${scoreBar("Tests", judge.test_score)}
        ${scoreBar("Architecture", judge.architecture_score)}
      </div>
    `;
  }

  function scoreBar(label, value) {
    if (value == null) return "";
    const pct = Math.round(value * 100);
    return `
      <div style="margin-bottom:10px">
        <div style="display:flex;justify-content:space-between;font-size:13px">
          <span>${esc(label)}</span><span>${pct}%</span>
        </div>
        <div class="score-bar"><div class="fill" style="width:${pct}%"></div></div>
      </div>`;
  }

  // ---- Tasks list ------------------------------------------------------------
  async function renderTasks() {
    $app.innerHTML = `<div class="loading">Loading tasks…</div>`;
    try {
      const tasks = await api("/api/tasks");
      $app.innerHTML = `
        <div class="panel"><h2>Tasks</h2></div>
        ${tasks.length === 0
          ? `<div class="panel" style="color:var(--muted)">No tasks yet. <a class="link" href="#/create">Create one</a>.</div>`
          : tasks.map((t) => `
              <div class="list-row" onclick="location.hash='#/tasks/${t.id}'">
                <div>
                  <div class="title">${esc(t.id.slice(0, 8))}</div>
                  <div class="sub">${esc(t.repository_url)} · ${esc(t.issue_url)}</div>
                </div>
                <span class="badge ${esc(t.status)}">${esc(t.status)}</span>
              </div>`).join("")}
      `;
    } catch (err) {
      $app.innerHTML = `<div class="error-box">${esc(err.message)}</div>`;
    }
  }

  // ---- Metrics ---------------------------------------------------------------
  async function renderMetrics() {
    $app.innerHTML = `<div class="loading">Loading metrics…</div>`;
    try {
      const [m, d] = await Promise.all([
        api("/api/dashboard/metrics"),
        api("/api/dashboard/tasks"),
      ]);
      const summary = d.summary || {};
      $app.innerHTML = `
        <div class="panel"><h2>Metrics</h2></div>
        <div class="metrics-grid">
          <div class="stat"><div class="label">Total Tasks</div><div class="value">${esc(summary.total_tasks ?? 0)}</div></div>
          <div class="stat"><div class="label">Success Rate</div><div class="value">${formatPercent(summary.task_success_rate)}</div></div>
          <div class="stat"><div class="label">Total Tokens</div><div class="value">${fmtNum(m.total_tokens)}</div></div>
          <div class="stat"><div class="label">Total Cost</div><div class="value">$${esc((m.total_cost_usd ?? 0).toFixed(4))}</div></div>
        </div>
        <div class="panel"><h3>Tokens by Agent</h3>
          <table><thead><tr><th>Agent</th><th>Tokens</th></tr></thead><tbody>
          ${Object.entries(m.tokens_by_agent || {}).map(([a, v]) =>
            `<tr><td>${esc(a)}</td><td>${fmtNum(v)}</td></tr>`).join("") || "<tr><td colspan=2>—</td></tr>"}
          </tbody></table>
        </div>
      `;
    } catch (err) {
      $app.innerHTML = `<div class="error-box">${esc(err.message)}</div>`;
    }
  }

  // ---- utils ------------------------------------------------------------------
  function formatDuration(sec) {
    sec = Math.max(0, Math.floor(sec));
    const m = Math.floor(sec / 60), s = sec % 60, h = Math.floor(m / 60);
    return `${String(h).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }
  function formatScore(v) { return v == null ? "—" : `${Math.round(v * 100)}%`; }
  function formatPercent(v) { return v == null ? "—" : `${Math.round((v || 0) * 100)}%`; }
  function fmtNum(n) { return (n ?? 0).toLocaleString(); }

  window.addEventListener("hashchange", render);
  window.addEventListener("load", render);
})();
