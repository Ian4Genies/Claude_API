const $ = (id) => document.getElementById(id);

const state = {
  staticFiles: [
    "data/Prompt_01/Prompt - Authored Head Tagging.md",
    "data/Prompt_01/Prompt - Authored Head Atlas.md",
    "data/Prompt_01/Atlas_0_1024_1.png",
    "data/Prompt_01/Atlas_0_1024_2.png",
  ],
  matches: [],
  pairStatus: {},
};

function log(msg) {
  const el = $("log");
  el.textContent += `${new Date().toLocaleTimeString()}  ${msg}\n`;
  el.scrollTop = el.scrollHeight;
}

function renderStaticFiles() {
  const list = $("staticFiles");
  list.innerHTML = "";
  state.staticFiles.forEach((file, idx) => {
    const li = document.createElement("li");
    li.innerHTML = `<span>${file}</span><button data-idx="${idx}">×</button>`;
    li.querySelector("button").onclick = () => {
      state.staticFiles.splice(idx, 1);
      renderStaticFiles();
    };
    list.appendChild(li);
  });
}

function payload() {
  const limitRaw = $("runLimit").value.trim();
  return {
    name: $("recipeName").value.trim(),
    static_files: state.staticFiles,
    left_folder: $("leftFolder").value.trim(),
    right_folder: $("rightFolder").value.trim(),
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

function renderPairs(matches = state.matches) {
  const body = $("pairsBody");
  body.innerHTML = "";
  matches.forEach((m) => {
    const tr = document.createElement("tr");
    const status = state.pairStatus[m.key] || "pending";
    const badgeClass = status === "ok" ? "ok" : status === "error" ? "err" : status === "skipped" ? "warn" : "";
    tr.innerHTML = `
      <td>${m.key}</td>
      <td>${m.left.split(/[/\\]/).pop()}</td>
      <td>${m.right.split(/[/\\]/).pop()}</td>
      <td><span class="badge ${badgeClass}">${status}</span></td>
    `;
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
  $("recipeName").value = data.name;
  state.staticFiles = data.static_files || [];
  renderStaticFiles();
  $("leftFolder").value = data.left_folder || "";
  $("rightFolder").value = data.right_folder || "";
  $("suffixPattern").value = data.suffix_pattern || "_grp_head_view_\\d+$";
  $("outputDir").value = data.output_dir || "output";
  $("outputNaming").value = data.output_naming || "{pair_key}.json";
  $("skipExisting").checked = data.skip_existing !== false;
  log(`Loaded recipe: ${name}`);
}

async function scanPairs() {
  log("Scanning folders...");
  const data = await api("/api/scan-pairs", {
    left_folder: $("leftFolder").value.trim(),
    right_folder: $("rightFolder").value.trim(),
    suffix_pattern: $("suffixPattern").value.trim(),
  });

  $("statMatches").textContent = data.match_count;
  $("statLeftOnly").textContent = data.left_only_count;
  $("statRightOnly").textContent = data.right_only_count;
  $("statStatus").textContent = data.is_clean ? "Clean" : "Gaps";
  state.matches = data.matches;
  state.pairStatus = {};
  renderPairs();
  log(`Found ${data.match_count} pairs (${data.left_only_count} left-only, ${data.right_only_count} right-only)`);
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
    const pct = total ? Math.round((job.current / total) * 100) : 0;
    $("progressBar").style.width = `${pct}%`;
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
    await pollJob(data.job_id, Number($("statMatches").textContent) || undefined);
  } catch (err) {
    log(`Error: ${err.message}`);
  } finally {
    $("runBtn").disabled = false;
  }
}

async function inspectFolder(inputId) {
  const folder = $(inputId).value.trim();
  log(`Inspecting ${folder}...`);
  const data = await api("/api/inspect-folder", { folder });
  log(`${data.count} images. Sample: ${data.sample_stems.slice(0, 3).join(", ")}`);
}

$("addStaticBtn").onclick = () => {
  const val = $("staticFileInput").value.trim();
  if (!val) return;
  state.staticFiles.push(val);
  $("staticFileInput").value = "";
  renderStaticFiles();
};

document.querySelectorAll("[data-inspect]").forEach((btn) => {
  btn.onclick = () => inspectFolder(btn.dataset.inspect);
});

$("scanBtn").onclick = () => scanPairs().catch((e) => log(e.message));
$("dryRunBtn").onclick = () => dryRun().catch((e) => log(e.message));
$("runBtn").onclick = () => runBatch();
$("loadRecipeBtn").onclick = () => loadRecipe($("recipeSelect").value).catch((e) => log(e.message));

renderStaticFiles();
loadRecipes().then(() => loadRecipe("prompt_01_head_tagging").catch(() => {})).then(() => scanPairs().catch(() => {}));
