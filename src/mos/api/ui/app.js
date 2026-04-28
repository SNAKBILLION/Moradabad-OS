const $ = (id) => document.getElementById(id);
let pollTimer = null;

function apiHeaders() {
  return { "Content-Type": "application/json", "x-api-key": $("api_key").value.trim() };
}

function setMsg(el, text, cls) {
  el.textContent = text;
  el.className = "msg " + (cls || "info");
}

async function submitJob() {
  const btn = $("submitBtn");
  btn.disabled = true;
  setMsg($("submitMsg"), "Submitting...", "info");
  try {
    const res = await fetch("/jobs", {
      method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify({
        owner_id: $("owner_id").value.trim(),
        brief_text: $("brief").value.trim(),
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      setMsg($("submitMsg"), `Error ${res.status}: ${JSON.stringify(data)}`, "err");
      return;
    }
    $("job_id").value = data.job_id;
    setMsg($("submitMsg"), `Job created: ${data.job_id}`, "ok");
    refreshStatus();
  } catch (e) {
    setMsg($("submitMsg"), "Network error: " + e.message, "err");
  } finally {
    btn.disabled = false;
  }
}

async function refreshStatus() {
  const jid = $("job_id").value.trim();
  if (!jid) { setMsg($("status"), "Enter a job ID first", "err"); return; }
  try {
    const res = await fetch(`/jobs/${jid}`, { headers: apiHeaders() });
    const data = await res.json();
    if (!res.ok) {
      setMsg($("status"), `Error ${res.status}: ${JSON.stringify(data)}`, "err");
      return;
    }
    renderStatus(data);
    return data;
  } catch (e) {
    setMsg($("status"), "Network error: " + e.message, "err");
  }
}

function renderStatus(data) {
  setMsg($("status"), `Job ${data.job_id} — status: ${data.status}`,
    data.status === "complete" ? "ok" : data.status === "failed" ? "err" : "info");

  const tbl = $("stages");
  tbl.innerHTML = "<tr><th>Stage</th><th>Status</th><th>Started</th><th>Finished</th><th>Error</th></tr>";
  for (const st of data.stages || []) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${st.name}</td>
      <td><span class="tag ${st.status}">${st.status}</span></td>
      <td>${st.started_at || "—"}</td>
      <td>${st.finished_at || "—"}</td>
      <td>${st.error || ""}</td>`;
    tbl.appendChild(tr);
  }

  const art = $("artifacts");
  art.innerHTML = "";
  const urls = data.artifact_urls || {};
  for (const [key, val] of Object.entries(urls)) {
    const row = document.createElement("div");
    row.className = "artifact-row";
    if (val) {
      row.innerHTML = `<span>${key}</span><a href="${val}" target="_blank" rel="noopener">open</a>`;
    } else {
      row.innerHTML = `<span>${key}</span><span style="color:#999">(none)</span>`;
    }
    art.appendChild(row);
  }

  const rw = $("renderWrap");
  rw.innerHTML = "";
  const stl = urls.stl || "";
  const m = stl.match(/\/cad\/([0-9a-f-]+)\.stl/);
  if (m && data.status === "complete") {
    const specId = m[1];
    const renderUrl = `/jobs/${data.job_id}/render/${specId}.png`;
    const img = document.createElement("img");
    img.src = renderUrl + "?t=" + Date.now();
    img.alt = "render preview";
    img.onerror = () => { rw.innerHTML = "<p style='color:#999'>Render preview not available via API. Use S3 link if present.</p>"; };
    rw.appendChild(img);
  }
}

function toggleAutoPoll() {
  const btn = $("autoBtn");
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
    btn.textContent = "Auto-poll";
    return;
  }
  btn.textContent = "Stop polling";
  pollTimer = setInterval(async () => {
    const data = await refreshStatus();
    if (data && (data.status === "complete" || data.status === "failed")) {
      clearInterval(pollTimer);
      pollTimer = null;
      btn.textContent = "Auto-poll";
    }
  }, 5000);
}

$("submitBtn").addEventListener("click", submitJob);
$("refreshBtn").addEventListener("click", refreshStatus);
$("autoBtn").addEventListener("click", toggleAutoPoll);