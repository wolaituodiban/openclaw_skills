---
name: local-image-model
description: "Resolve, start, invoke, and release a local vllm-omni image-generation service through MCP tools."
---


# OpenClaw Configuration

```json
{
  "mcp": {
    "servers": {
      "local-image-model": {
        "command": "{python_path}",
        "args": ["-m", "scripts.mcp_server"],
        "cwd": "{skill_path}",
        "env": {
          "PATH": "{vllm_path}"
        }
      }
    }
  }
}
```