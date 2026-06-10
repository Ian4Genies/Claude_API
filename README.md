# Claude API Starter

Minimal Python starter for Anthropic Claude API calls, with a batch runner for multimodal vision jobs.

## Setup

```bash
py -m venv .venv
.venv\Scripts\activate
pip install -e .
copy .env.example .env
```

Set `ANTHROPIC_API_KEY` in `.env`.

## Batch Runner UI

**Restart (easiest):** double-click `restart-ui.bat` or run:

```powershell
.\restart-ui.ps1
```

**Manual start:**

```bash
uvicorn runner.app:app --reload
```

Open http://127.0.0.1:8000

- Load the **prompt_01_head_tagging** recipe (preconfigured)
- **Inspect** folders to preview image counts
- **Scan Pairs** auto-matches front/side renders by stripping `_grp_head_view_<angle>`
- **Dry Run** validates static files + pair count without API calls
- **Run Batch** sends Prompt_01 assets + each image pair to Claude, extracts JSON, saves to `output/prompt_01/{pair_key}.json`
- **Skip existing** resumes interrupted runs

## CLI

```bash
python -m runner.cli scan --recipe prompt_01_head_tagging
python -m runner.cli dry-run --recipe prompt_01_head_tagging
python -m runner.cli run --recipe prompt_01_head_tagging --limit 1
python -m runner.cli run --recipe prompt_01_head_tagging --pair african_female_0001
```

## Recipe format

`recipes/prompt_01_head_tagging.yaml`:

```yaml
name: prompt_01_head_tagging
static_files:          # attached to every run
  - data/Prompt_01/Prompt - Authored Head Tagging.md
  - data/Prompt_01/Prompt - Authored Head Atlas.md
  - data/Prompt_01/Atlas_0_1024_1.png
  - data/Prompt_01/Atlas_0_1024_2.png
pair_folders:
  left: data/Render_FrontView
  right: data/Render_SideView
  suffix_pattern: _grp_head_view_\d+$
output_dir: output/prompt_01
output_naming: "{pair_key}.json"
skip_existing: true
```

## Simple API usage

```python
from src import message, stream_message

text = message("Summarize REST in one line.")
```

## Config

| Variable | Default |
|----------|---------|
| `ANTHROPIC_API_KEY` | required |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` |
| `ANTHROPIC_MAX_TOKENS` | `4096` |
