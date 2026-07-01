# 01 — Requirements: local-image-model

## 1. Project name

`local-image-model` — 本地图像模型mcp服务以及skill

## 2. Problem statement

openclaw没有管理本地图像模型的skill和mcp，不知道本地有什么缓存、不知道本地有什么服务

## 3. Goals

1. 探查本地modelscope模型缓存
2. 列举本地vllm-omni模型服务
3. 启动本地vllm-omni模型服务
4. 调用本地vllm-omni模型服务
5. 释放本地vllm-omni模型服务
6. 将1-5封装成mcp服务
7. skill提供mcp的配置和使用方法

## 4. Non-goals

- 权限
- 多GPU
- 多服务
- huggingface模型支持

## 5. Functional requirements



| ID | Requirement | Priority | Acceptance criteria |
|----|-------------|----------|---------------------|
| FR-1 | 探查本地modelscope模型缓存 | must | 返回REPO ID、 SIZE ON DIS、LOCAL PAT、加载状态 |
| FR-2 | 列举本地vllm-omni模型服务 | must | 返回PID、 REPO ID、 LOCAL PATH、服务状态 |
| FR-3 | 启动本地vllm-omni模型服务 | must | 根据REPO ID 启动vllm-omni服务。如果当前没有模型服务，则异步非阻塞启动模型服务子进程，返回PID、 REPO ID、 LOCAL PATH；否则返回错误信息，告知当前服务PID、 REPO ID、 LOCAL PATH，提示caller先release再start |
| FR-4 | 调用本地vllm-omni模型服务 | must | 支持openai API以及vllm-omni扩展参数，调用本地模型服务，根据image/images参数情况，路由到generate/edit api上 |
| FR-5 | 释放本地vllm-omni模型服务 | must | 释放本地服务 |

## 6. Non-functional requirements

| ID | Category | Requirement | Measure |
|----|----------|-------------|---------|

## 7. Users / actors

agent/human/openclaw gateway

## 8. Open questions

- [ ] None

## 9. Glossary

- **vllm-omni** ： vLLM-Omni is a framework that extends its support for omni-modality model inference and serving。https://docs.vllm.ai/projects/vllm-omni/en/stable/