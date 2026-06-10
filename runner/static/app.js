const $ = (id) => document.getElementById(id);
const IMAGE_EXT = /\.(png|jpe?g|webp|gif)$/i;

const state = {
  staticFiles: [],
  folders: [],
  matches: [],
  folderLabels: [],
  pairStatus: {},
  selectedPairKey: null,
  selectedStatic: null,
  suppressHistory: false,
};

const history = { past: [], future: [], limit: 60 };

const browse = {
  mode: "file",
  multi: false,
  folderIdx: null,
  cwd: "",
  selected: null,
  selectedSet: new Set(),
};

function snapshot() {
  return JSON.stringify({
    recipeName: $("recipeName").value,
    staticFiles: [...state.staticFiles],
    folders: state.folders.map((f) => ({ ...f })),
    suffixPattern: $("suffixPattern").value,
    outputDir: $("outputDir").value,
    outputNaming: $("outputNaming").value,
    skipExisting: $("skipExisting").checked,
    runLimit: $("runLimit").value,
  });
}

function applySnapshot(raw) {
  const data = JSON.parse(raw);
  state.suppressHistory = true;
  $("recipeName").value = data.recipeName;
  state.staticFiles = data.staticFiles;
  state.folders = data.folders;
  $("suffixPattern").value = data.suffixPattern;
  $("outputDir").value = data.outputDir;
  $("outputNaming").value = data.outputNaming;
  $("skipExisting").checked = data.skipExisting;
  $("runLimit").value = data.runLimit || "";
  renderStaticFiles();
  renderFolders();
  updateHistoryButtons();
  state.suppressHistory = false;
}

function commitHistory() {
  if (state.suppressHistory) return;
  const current = snapshot();
  const top = history.past[history.past.length - 1];
  if (top === current) return;
  history.past.push(current);
  if (history.past.length > history.limit) history.past.shift();
  history.future = [];
  updateHistoryButtons();
}

function undo() {
  if (history.past.length < 2) return;
  history.future.push(history.past.pop());
  applySnapshot(history.past[history.past.length - 1]);
  log("Undo");
}

function redo() {
  if (!history.future.length) return;
  const next = history.future.pop();
  history.past.push(next);
  applySnapshot(next);
  log("Redo");
}

function updateHistoryButtons() {
  $("undoBtn").disabled = history.past.length < 2;
  $("redoBtn").disabled = !history.future.length;
}

function log(msg) {
  const el = $("log");
  el.textContent += `${new Date().toLocaleTimeString()}  ${msg}\n`;
  el.scrollTop = el.scrollHeight;
}

function isImage(path) {
  return IMAGE_EXT.test(path);
}

function mediaUrl(path) {
  return `/api/media?path=${encodeURIComponent(path)}`;
}

function fileName(path) {
  return path.split(/[/\\]/).pop();
}

function renderPreview(items, title) {
  $("previewTitle").textContent = title;
  const strip = $("previewStrip");
  strip.innerHTML = "";
  if (!items.length) {
    strip.innerHTML = `<div class="preview-empty">Nothing to preview</div>`;
    return;
  }
  items.forEach(({ path, label }) => {
    const card = document.createElement("div");
    card.className = "preview-card";
    if (isImage(path)) {
      card.innerHTML = `
        <img src="${mediaUrl(path)}" alt="${label || fileName(path)}" loading="lazy" />
        <div class="cap">${label || fileName(path)}</div>`;
    } else {
      card.classList.add("text-card");
      const ext = path.split(".").pop()?.toUpperCase() || "FILE";
      card.innerHTML = `
        <div class="doc">${ext}</div>
        <div class="cap">${label || fileName(path)}</div>`;
    }
    strip.appendChild(card);
  });
}

function previewStatic(path) {
  state.selectedStatic = path;
  state.selectedPairKey = null;
  renderStaticFiles();
  renderPairs();
  renderPreview([{ path, label: "static" }], `Static · ${fileName(path)}`);
}

function previewPair(match) {
  state.selectedPairKey = match.key;
  state.selectedStatic = null;
  renderStaticFiles();
  renderPairs();
  const items = state.folderLabels.map((label) => ({
    path: match.files[label],
    label,
  }));
  renderPreview(items, `Pair · ${match.key}`);
}

function renderStaticFiles() {
  const list = $("staticFiles");
  list.innerHTML = "";
  state.staticFiles.forEach((file, idx) => {
    const li = document.createElement("li");
    li.className = `asset-item${state.selectedStatic === file ? " active" : ""}`;
    const thumb = isImage(file)
      ? `<img class="thumb" src="${mediaUrl(file)}" alt="" loading="lazy" />`
      : `<div class="file-icon">${file.split(".").pop()?.toUpperCase() || "?"}</div>`;
    li.innerHTML = `
      ${thumb}
      <span class="name">${file}</span>
      <button class="remove" title="Remove">×</button>`;
    li.onclick = (e) => {
      if (e.target.classList.contains("remove")) return;
      previewStatic(file);
    };
    li.querySelector(".remove").onclick = (e) => {
      e.stopPropagation();
      mutate(() => state.staticFiles.splice(idx, 1));
    };
    list.appendChild(li);
  });
}

function renderFolders() {
  const wrap = $("folderList");
  wrap.innerHTML = "";
  state.folders.forEach((folder, idx) => {
    const row = document.createElement("div");
    row.className = "folder-row";
    row.innerHTML = `
      <input class="label-input" value="${folder.label}" placeholder="label" data-idx="${idx}" data-field="label" />
      <input value="${folder.path}" placeholder="data/..." data-idx="${idx}" data-field="path" />
      <button class="btn-ghost sm" data-browse="${idx}" title="Browse">…</button>
      <button class="btn-ghost sm" data-inspect="${idx}" title="Inspect">↗</button>
      <button class="btn-ghost sm" data-remove="${idx}" title="Remove">×</button>`;
    row.querySelectorAll("input").forEach((input) => {
      input.onchange = () => {
        mutate(() => {
          folder[input.dataset.field] = input.value.trim();
        });
      };
    });
    row.querySelector(`[data-browse="${idx}"]`).onclick = () => openBrowse({ mode: "folder", folderIdx: idx, startPath: folder.path });
    row.querySelector(`[data-inspect="${idx}"]`).onclick = () => inspectFolder(idx);
    row.querySelector(`[data-remove="${idx}"]`).onclick = () => {
      if (state.folders.length <= 2) {
        log("Need at least 2 pair folders");
        return;
      }
      mutate(() => state.folders.splice(idx, 1));
    };
    wrap.appendChild(row);
  });
}

async function fetchBrowse(path = "") {
  const q = path ? `?path=${encodeURIComponent(path)}` : "";
  const res = await fetch(`/api/browse${q}`);
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Browse failed");
  return data;
}

function renderBreadcrumb(data) {
  const el = $("browseBreadcrumb");
  el.innerHTML = "";
  const parts = data.path ? data.path.split("/") : [];
  const mkBtn = (label, path, active = false) => {
    const btn = document.createElement("button");
    btn.textContent = label;
    if (active) btn.classList.add("active");
    btn.onclick = () => loadBrowse(path);
    el.appendChild(btn);
  };
  mkBtn("project", "", !data.path);
  let acc = "";
  parts.forEach((part, i) => {
    acc = acc ? `${acc}/${part}` : part;
    mkBtn(part, acc, i === parts.length - 1);
  });
}

function updateBrowseSelection() {
  const el = $("browseSelection");
  if (browse.mode === "folder") {
    el.textContent = browse.cwd ? browse.cwd : "project root";
    return;
  }
  if (browse.multi) {
    el.textContent = browse.selectedSet.size
      ? `${browse.selectedSet.size} file(s) selected`
      : "Click files to select (multi)";
    return;
  }
  el.textContent = browse.selected || "Click a file to select";
}

function renderBrowseList(data) {
  const list = $("browseList");
  list.innerHTML = "";
  browse.cwd = data.path;

  data.entries.forEach((entry) => {
    const row = document.createElement("div");
    const isSelected = browse.mode === "folder"
      ? false
      : browse.multi
        ? browse.selectedSet.has(entry.path)
        : browse.selected === entry.path;
    row.className = `browse-item${isSelected ? (browse.multi ? " checked" : " selected") : ""}`;
    row.innerHTML = `
      <span class="icon">${entry.kind === "dir" ? "📁" : entry.is_image ? "🖼" : "📄"}</span>
      <span>${entry.name}</span>
      <span class="meta">${entry.kind}</span>`;

    row.onclick = () => {
      if (entry.kind === "dir") {
        loadBrowse(entry.path);
        return;
      }
      if (browse.mode === "folder") return;
      if (browse.multi) {
        if (browse.selectedSet.has(entry.path)) browse.selectedSet.delete(entry.path);
        else browse.selectedSet.add(entry.path);
      } else {
        browse.selected = entry.path;
      }
      renderBrowseList(data);
      updateBrowseSelection();
    };

    row.ondblclick = () => {
      if (entry.kind === "dir") loadBrowse(entry.path);
      else if (browse.mode !== "folder") {
        browse.selected = entry.path;
        browse.selectedSet = new Set([entry.path]);
        confirmBrowse();
      }
    };

    row.onkeydown = (e) => {
      if (entry.kind === "dir" && e.key === "Enter") loadBrowse(entry.path);
    };

    list.appendChild(row);
  });

  updateBrowseSelection();
}

async function loadBrowse(path = "") {
  const data = await fetchBrowse(path);
  renderBreadcrumb(data);
  renderBrowseList(data);
}

function openBrowse({ mode = "file", multi = false, folderIdx = null, startPath = "" } = {}) {
  browse.mode = mode;
  browse.multi = multi;
  browse.folderIdx = folderIdx;
  browse.selected = null;
  browse.selectedSet = new Set();

  $("browseTitle").textContent = mode === "folder" ? "Browse folder" : multi ? "Browse files" : "Browse file";
  $("browseHint").textContent = mode === "folder"
    ? "Navigate and select the folder for this pair slot"
    : multi
      ? "Select one or more files to add as static assets"
      : "Select a file to add as a static asset";
  $("browseSelectFolderBtn").classList.toggle("hidden", mode !== "folder");
  $("browseConfirmBtn").textContent = mode === "folder" ? "Use folder" : multi ? "Add selected" : "Select";

  $("browseModal").classList.remove("hidden");
  loadBrowse(startPath || "").catch((e) => log(e.message));
}

function closeBrowse() {
  $("browseModal").classList.add("hidden");
}

function confirmBrowse() {
  if (browse.mode === "folder") {
    const path = browse.cwd || "";
    if (browse.folderIdx !== null) {
      mutate(() => {
        state.folders[browse.folderIdx].path = path;
        if (!state.folders[browse.folderIdx].label.trim()) {
          state.folders[browse.folderIdx].label = path.split("/").pop() || "folder";
        }
      });
      log(`Folder set: ${path || "project root"}`);
    }
  } else if (browse.multi) {
    const paths = [...browse.selectedSet];
    if (!paths.length && browse.selected) paths.push(browse.selected);
    if (!paths.length) return;
    mutate(() => {
      paths.forEach((p) => {
        if (!state.staticFiles.includes(p)) state.staticFiles.push(p);
      });
    });
    log(`Added ${paths.length} static file(s)`);
  } else {
    const path = browse.selected;
    if (!path) return;
    $("staticFileInput").value = path;
    mutate(() => {
      if (!state.staticFiles.includes(path)) state.staticFiles.push(path);
    });
    log(`Added static: ${path}`);
  }
  closeBrowse();
}

function mutate(fn) {
  fn();
  renderStaticFiles();
  renderFolders();
  commitHistory();
}

function payload() {
  const limitRaw = $("runLimit").value.trim();
  return {
    name: $("recipeName").value.trim(),
    static_files: state.staticFiles,
    folders: state.folders,
    suffix_pattern: $("suffixPattern").value.trim(),
    output_dir: $("outputDir").value.trim(),
    output_naming: $("outputNaming").value.trim(),
    skip_existing: $("skipExisting").checked,
    limit: limitRaw ? Number(limitRaw) : null,
  };
}

async function api(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
  return data;
}

function renderStats(data) {
  const row = $("statsRow");
  row.innerHTML = `
    <div class="stat ok"><div class="value">${data.match_count}</div><div class="label">Matches</div></div>`;
  Object.entries(data.orphan_counts || {}).forEach(([label, count]) => {
    const cls = count ? "warn" : "ok";
    row.innerHTML += `
      <div class="stat ${cls}"><div class="value">${count}</div><div class="label">${label} only</div></div>`;
  });
  row.innerHTML += `
    <div class="stat"><div class="value">${data.is_clean ? "Clean" : "Gaps"}</div><div class="label">Consistency</div></div>`;
}

function renderPairsHeader() {
  const head = $("pairsHead");
  const labels = state.folderLabels.length ? state.folderLabels : ["files"];
  head.innerHTML = `<tr><th>Key</th>${labels.map((l) => `<th>${l}</th>`).join("")}<th>Status</th></tr>`;
}

function renderPairs(matches = state.matches) {
  renderPairsHeader();
  const body = $("pairsBody");
  body.innerHTML = "";
  matches.forEach((m) => {
    const tr = document.createElement("tr");
    if (state.selectedPairKey === m.key) tr.classList.add("active");
    const status = state.pairStatus[m.key] || "pending";
    const badgeClass = status === "ok" ? "ok" : status === "error" ? "err" : status === "skipped" ? "warn" : "pending";
    const fileCells = state.folderLabels
      .map((label) => `<td>${fileName(m.files[label] || "")}</td>`)
      .join("");
    tr.innerHTML = `
      <td>${m.key}</td>
      ${fileCells}
      <td><span class="badge ${badgeClass}">${status}</span></td>`;
    tr.onclick = () => previewPair(m);
    body.appendChild(tr);
  });
}

async function loadRecipes() {
  const res = await fetch("/api/recipes");
  const data = await res.json();
  const select = $("recipeSelect");
  select.innerHTML = "";
  data.recipes.forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    select.appendChild(opt);
  });
}

async function loadRecipe(name) {
  const res = await fetch(`/api/recipes/${name}`);
  if (!res.ok) throw new Error("Failed to load recipe");
  const data = await res.json();
  state.suppressHistory = true;
  $("recipeName").value = data.name;
  state.staticFiles = data.static_files || [];
  state.folders = data.folders?.length ? data.folders : [
    { label: "front", path: "data/Render_FrontView" },
    { label: "side", path: "data/Render_SideView" },
  ];
  $("suffixPattern").value = data.suffix_pattern || "_grp_head_view_\\d+$";
  $("outputDir").value = data.output_dir || "output";
  $("outputNaming").value = data.output_naming || "{pair_key}.json";
  $("skipExisting").checked = data.skip_existing !== false;
  renderStaticFiles();
  renderFolders();
  history.past = [snapshot()];
  history.future = [];
  updateHistoryButtons();
  state.suppressHistory = false;
  log(`Loaded recipe: ${name}`);
}

async function saveRecipe() {
  const data = await api("/api/recipes/save", payload());
  log(`Saved ${data.saved}`);
  await loadRecipes();
}

async function scanPairs() {
  if (state.folders.length < 2) throw new Error("Add at least 2 folders");
  log("Scanning folders...");
  const data = await api("/api/scan-pairs", {
    folders: state.folders,
    suffix_pattern: $("suffixPattern").value.trim(),
  });

  renderStats(data);
  state.folderLabels = data.folder_labels;
  state.matches = data.matches;
  state.pairStatus = {};
  $("folderSummary").textContent = state.folderLabels.join(" · ");
  renderPairs();
  if (state.matches[0]) previewPair(state.matches[0]);
  log(`Found ${data.match_count} complete pairs across ${state.folderLabels.length} folders`);
}

async function dryRun() {
  log("Dry run...");
  const data = await api("/api/dry-run", payload());
  log(`Pairs: ${data.pair_count}, missing static: ${data.static_missing.length}`);
  if (data.static_missing.length) log(`Missing: ${data.static_missing.join(", ")}`);
}

async function pollJob(jobId, totalHint) {
  while (true) {
    const res = await fetch(`/api/run/${jobId}`);
    const job = await res.json();
    const total = job.total || totalHint || 1;
    $("progressBar").style.width = `${total ? Math.round((job.current / total) * 100) : 0}%`;
    $("runSummary").textContent = `Running ${job.current}/${total} · ok ${job.succeeded} · skipped ${job.skipped} · failed ${job.failed}`;
    job.items.forEach((item) => {
      state.pairStatus[item.pair_key] = item.skipped ? "skipped" : item.status;
    });
    renderPairs();
    if (job.status === "done") {
      log(`Done. ok=${job.result.succeeded} skipped=${job.result.skipped} failed=${job.result.failed}`);
      return;
    }
    if (job.status === "error") {
      log(`Job error: ${job.error}`);
      return;
    }
    await new Promise((r) => setTimeout(r, 1200));
  }
}

async function runBatch() {
  $("runBtn").disabled = true;
  try {
    log("Starting batch...");
    const data = await api("/api/run", payload());
    await pollJob(data.job_id, Number($("statMatches")?.textContent) || state.matches.length);
  } catch (err) {
    log(`Error: ${err.message}`);
  } finally {
    $("runBtn").disabled = false;
  }
}

async function inspectFolder(idx) {
  const folder = state.folders[idx];
  if (!folder?.path) return;
  log(`Inspecting ${folder.label}: ${folder.path}...`);
  const data = await api("/api/inspect-folder", { folder: folder.path });
  log(`${data.count} images in ${folder.label}`);
  if (data.sample_previews?.length) {
    renderPreview(
      data.sample_previews.map((p) => ({ path: p.path, label: folder.label })),
      `Folder · ${folder.label}`,
    );
  }
}

$("addStaticBtn").onclick = () => {
  const val = $("staticFileInput").value.trim();
  if (!val) return;
  mutate(() => state.staticFiles.push(val));
  $("staticFileInput").value = "";
};

$("browseStaticBtn").onclick = () => {
  const start = $("staticFileInput").value.trim();
  const base = start.includes("/") ? start.split("/").slice(0, -1).join("/") : start;
  openBrowse({ mode: "file", multi: true, startPath: base || "data" });
};

$("browseCloseBtn").onclick = closeBrowse;
$("browseConfirmBtn").onclick = confirmBrowse;
$("browseSelectFolderBtn").onclick = confirmBrowse;
$("browseModal").onclick = (e) => {
  if (e.target === $("browseModal")) closeBrowse();
};

$("addFolderBtn").onclick = () => {
  mutate(() => state.folders.push({ label: `view${state.folders.length + 1}`, path: "" }));
};

$("undoBtn").onclick = undo;
$("redoBtn").onclick = redo;
$("scanBtn").onclick = () => scanPairs().catch((e) => log(e.message));
$("dryRunBtn").onclick = () => dryRun().catch((e) => log(e.message));
$("runBtn").onclick = () => runBatch();
$("loadRecipeBtn").onclick = () => loadRecipe($("recipeSelect").value).then(() => scanPairs()).catch((e) => log(e.message));
$("saveRecipeBtn").onclick = () => saveRecipe().catch((e) => log(e.message));
$("clearPreviewBtn").onclick = () => {
  state.selectedPairKey = null;
  state.selectedStatic = null;
  renderStaticFiles();
  renderPairs();
  renderPreview([], "Preview");
};

document.querySelectorAll("[data-track]").forEach((el) => {
  el.addEventListener("change", commitHistory);
});

document.addEventListener("keydown", (e) => {
  if (e.ctrlKey && e.key === "z") { e.preventDefault(); undo(); }
  if (e.ctrlKey && e.key === "y") { e.preventDefault(); redo(); }
  if (e.key === "Escape" && !$("browseModal").classList.contains("hidden")) closeBrowse();
});

loadRecipes()
  .then(() => loadRecipe("prompt_01_head_tagging"))
  .then(() => scanPairs())
  .catch(() => {});
