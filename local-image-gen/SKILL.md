---
name: local-image-gen
description: "Resolve, start, invoke, and release a local vllm-omni image-generation service through MCP tools."
---

# local-image-gen

Drive a local vllm-omni image-generation service (text-to-image or image-edit)
through five MCP tools. The OpenClaw gateway owns the MCP server lifecycle via
stdio; the MCP server owns the vllm-omni subprocess lifecycle.

## When to reach for this skill

- User wants to generate or edit images **locally** (no cloud API).
- A diffusion model (e.g. Z-Image-Turbo, Qwen-Image-Edit) is already cached on
  disk in HuggingFace or ModelScope layout.
- The user has a CUDA GPU and `vllm-omni` installed.

## MCP tools

| Tool | Purpose |
|------|---------|
| `start_service(model, timeoutMs, cache_dir)` | Resolve model on disk, spawn vllm-omni, poll until ready. Returns `{model, pid, port, bearer_token, cache_source, model_path, started_at}`. |
| `invoke_model(prompt, filename, model, size, outputFormat, count, timeoutMs, image, images, negative_prompt, num_inference_steps, guidance_scale, true_cfg_scale, seed)` | Call the running service's `/v1/images/generations` or `/v1/images/edits`. Returns `{path, b64_json}` (count=1) or `{paths[], b64_jsons[]}` (count>1). |
| `release_service(model)` | Kill the vllm-omni subprocess and remove service.json. Returns `{released, model, pid, port}`. |
| `list_running_services()` | Return all tracked service.json entries (including stale). |
| `list_local_models(model_dir)` | Walk a directory tree and return HF/MS layout model folders. |

## Workflow

1. `start_service("Tongyi-MAI/Z-Image-Turbo")` — resolves the model snapshot,
   picks a free port, spawns `vllm serve ...`, polls `/v1/models` until ready.
2. `invoke_model("a cat on the moon", "/tmp/cat.png")` — generates the image
   and writes it to the caller-supplied path.
3. `release_service("Tongyi-MAI/Z-Image-Turbo")` — tears down the subprocess.

## Authentication

No authentication required on the vllm-omni HTTP surface. The MCP server
connects to vllm-omni without `--api-key` or bearer tokens.

## Cache resolution

The 5-level chain: HF env → HF default → MS env → MS default → per-call
`cache_dir`. First on-disk hit wins; no network download.

## Error contract

All errors follow the vllm-omni HTTP error shape: `{error: {code, message}}`.
Upstream vllm-omni errors (4xx, 5xx) are surfaced verbatim — no transformation
or retry.

## Configuring in OpenClaw

1. Ensure the skill files are placed under `~/.openclaw/skills/local-image-gen/`:
   - `SKILL.md`
   - `local_image_gen/` Python package
   - `tests/` directory

2. **Edit `~/.openclaw/openclaw.json` and add the MCP server config**:

   ```json
   {
     "mcp": {
       "servers": {
         "local-image-gen": {
           "command": "<PYTHON_ABS_PATH>",
           "args": ["-m", "local_image_gen.mcp_server"],
           "cwd": "<SKILL_ROOT_DIR>",
           "env": {
             "PATH": "/home/cxt/.venv/bin:/usr/local/bin:/usr/bin:/bin"
           }
         }
       }
     }
   }
   ```

   Replace placeholders:
   - `<PYTHON_ABS_PATH>` → absolute path to your Python interpreter (e.g. `/home/yourname/.venv/bin/python`). **Do not** use `~` — OpenClaw does not expand it.
   - `<SKILL_ROOT_DIR>` → absolute path to the skill root directory (the one containing `local_image_gen/` and `SKILL.md`).

   > **Critical constraints**:
   > - `command` must be an **absolute path**.
   > - `args` must use `-m local_image_gen.mcp_server` (module name), **not** a file path like `-m /path/to/mcp_server.py`.
   > - `cwd` must point to the skill root so Python can find the `local_image_gen` package.
   > - **`env.PATH` must include the directory containing the `vllm` binary** (e.g. `/home/cxt/.venv/bin`). The MCP server runs as a separate process and does not inherit OpenClaw's `pathPrepend` or shell PATH.

3. Edit `~/.openclaw/openclaw.json` and **append** `"local-image-gen"` to the `agents.defaults.skills` array:

   ```json
   {
     "agents": {
       "defaults": {
         "skills": [
           "skill-creator",
           "local-image-gen"
         ]
       }
     }
   }
   ```

   > **Note**: `agents.defaults.skills` is a **protected config path** and cannot be modified via `gateway config.patch`. You must edit the file manually.

4. Restart the Gateway to pick up changes:
   ```bash
   openclaw gateway restart
   ```

5. **Verification**: After restart, check that the MCP server connects successfully (`Initialized...` / `tools registered` in logs).

   **OpenClaw MCP tool naming convention**: Loaded tools are prefixed with the server name:
   - `local-image-gen__start_service`
   - `local-image-gen__invoke_model`
   - `local-image-gen__release_service`
   - `local-image-gen__list_running_services`
   - `local-image-gen__list_local_models`

   Verify with `openclaw mcp probe local-image-gen`.

## Requirements

- `vllm-omni` on PATH
- CUDA GPU with enough VRAM for the target model
- Model weights already cached on disk (HF or MS layout)
