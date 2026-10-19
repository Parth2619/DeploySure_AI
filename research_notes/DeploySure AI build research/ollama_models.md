# Ollama on Windows 11 for structured JSON (DeploySure AI), as of Oct 2026

## 1. Windows install, pull, port, health check

### Takeaway
Install with `winget install --id Ollama.Ollama -e` or OllamaSetup.exe (no admin needed); it runs in the background and serves on http://localhost:11434. Check with `ollama --version`, `ollama ps` or a GET to the port.

### Cited Findings
- OllamaSetup.exe needs no Administrator rights, installs to the home dir, runs in background; `ollama` works in cmd/PowerShell. Needs Windows 10 22H2+; about 4GB for binaries plus models — [Ollama Windows docs](https://docs.ollama.com/windows)
- API at `http://localhost:11434`; models stored in `%HOMEPATH%\.ollama`; `OLLAMA_MODELS` changes the location — [Ollama Windows docs](https://docs.ollama.com/windows)
- NVIDIA GPU needs driver 551.61+; AMD uses ROCm or Vulkan. No GPU means CPU fallback — [Ollama Windows docs](https://docs.ollama.com/windows)
- Winget: `winget install --id Ollama.Ollama -e` (`-e` avoids the separate Ollama.Ollama.Portable package); same build as the website download (about 1.45 GB) — [pureinfotech guide](https://pureinfotech.com/install-ollama-run-local-ai-models-windows-11/) (secondary source; search snippet, not fetched in full)
- `ollama ps` lists loaded models and a PROCESSOR column (100% CPU / 100% GPU / split). Server binds 127.0.0.1:11434 by default. The FAQ has no dedicated health command — [Ollama FAQ](https://docs.ollama.com/faq)
- No documented silent-install flag, only `/DIR`; a standalone zip exists for service-style use — [Ollama Windows docs](https://docs.ollama.com/windows)

### Inferences
- Health check for the wrapper: `GET http://localhost:11434/` (Ollama replies "Ollama is running", from my memory of the server, not verified in these sources) or `ollama.list()` in Python, with a clear error if connection fails.
- `ollama ps` PROCESSOR column tells Manc immediately whether she is on CPU.

### Gaps
- Exact "Ollama is running" root response text not confirmed from a fetched source.

## 2. Python client, structured outputs, options, keep_alive; ollama vs langchain-ollama

### Takeaway
Use the plain `ollama` package (latest 0.6.3, 29 Sep 2026) with `chat(format=Model.model_json_schema(), options={'temperature':0,'seed':42}, keep_alive=...)` and validate with pydantic. It is lighter than langchain-ollama. LangGraph does not need langchain-ollama.

### Cited Findings
- PyPI `ollama` latest 0.6.3, released Sep 29, 2026, Python >=3.8 — [PyPI ollama](https://pypi.org/project/ollama/)
- PyPI `langchain-ollama` latest 1.1.0, released Apr 7, 2026, Python >=3.10 — [PyPI langchain-ollama](https://pypi.org/project/langchain-ollama/)
- Structured outputs: pass a JSON schema (e.g. pydantic `model_json_schema()`) in `format`; validate response with `Model.model_validate_json(response.message.content)`; set temperature 0; docs also suggest putting the schema in the prompt text to ground the model — [Ollama structured outputs docs](https://docs.ollama.com/capabilities/structured-outputs)
- Docs example pattern: `chat(model=..., format=ImageDescription.model_json_schema(), options={'temperature': 0})` — [Ollama structured outputs docs](https://docs.ollama.com/capabilities/structured-outputs)
- `keep_alive` on `/api/chat` or `/api/generate` accepts a duration string ("10m"), seconds, negative for forever, 0 to unload; default is 5 minutes; env var `OLLAMA_KEEP_ALIVE` sets the server default — [Ollama FAQ](https://docs.ollama.com/faq)
- `think=False` on chat/generate requests no thinking output "if the model permits it"; thinking models return `message.thinking` separately from `message.content` — [Ollama thinking docs](https://docs.ollama.com/capabilities/thinking)

### Inferences
- Snippet (assembled from the documented pieces above; not run by me):
```python
from ollama import chat
from pydantic import BaseModel

class Out(BaseModel):
    decision: str
    reason: str

r = chat(model="qwen2.5:7b",
         messages=[{"role": "user", "content": prompt + "\nReply as JSON matching: " + str(Out.model_json_schema())}],
         format=Out.model_json_schema(),
         options={"temperature": 0, "seed": 42},
         keep_alive="30m")
out = Out.model_validate_json(r.message.content)
```
- Recommendation: plain `ollama` + `pydantic` (pydantic is already a dependency of the ollama package, per my memory, not confirmed in sources). Avoid `langchain-ollama` (`ChatOllama.with_structured_output`) because it adds the langchain-core stack for no gain. The CLAUDE.md wants minimal dependencies.
- Wrapper design: `ask(prompt, schema=None)`: if schema is a dict, pass as `format`; else `format="json"`. Parse, validate, retry once on failure, then return the deterministic fallback and note it in the trace.

### Gaps
- Did not verify the dependency list of the `ollama` package (PyPI page did not list it).
- No source fetched comparing `with_structured_output` internals; the recommendation is a judgement call.

## 3. Model choice for CPU laptops

### Takeaway
Default to `qwen2.5:7b` only if the laptop has 16GB RAM and tolerates a slow answer; otherwise `qwen2.5:3b` or `llama3.2:3b`. Avoid thinking models (qwen3) unless `think=False` is used. Measure on Manc's machine with `ollama run <model> --verbose`.

### Cited Findings
- qwen2.5 sizes: 0.5b 398MB, 1.5b 986MB, 3b 1.9GB, 7b 4.7GB, 32K context; default tag is the 7b — [Ollama qwen2.5](https://ollama.com/library/qwen2.5)
- qwen3 sizes: 0.6b 523MB, 1.7b 1.4GB, 4b 2.5GB, 8b 5.2GB; family is tagged "thinking" and "tools" — [Ollama qwen3](https://ollama.com/library/qwen3)
- llama3.2: 1b 1.3GB, 3b 2.0GB, 128K context — [Ollama llama3.2](https://ollama.com/library/llama3.2)
- phi4-mini 3.8B: 2.5GB, 128K context, function calling; page does not mention structured output; needs Ollama 0.5.13+ — [Ollama phi4-mini](https://ollama.com/library/phi4-mini)
- gemma3: 1b 806MB, 4b 3.4GB, 12b 8.2GB — [Ollama gemma3](https://ollama.com/library/gemma3)
- The Ollama structured-outputs docs example uses `model='gemma4'`, so a Gemma 4 exists in the library by Oct 2026; I did not fetch its sizes — [Ollama structured outputs docs](https://docs.ollama.com/capabilities/structured-outputs)
- CPU speed claims are inconsistent across aggregator guides: llama3.2 3B about 10 tok/s on an i7-12700 in one guide vs 25-45 on "a typical laptop" in another — [PromptQuorum](https://www.promptquorum.com/local-llms/best-cpu-only-llm)
- The most concrete measurement: phi4 3.8B on a CPU-only Ubuntu box got 6.90 tok/s generation (20.06 prompt eval) — [It's FOSS test](https://itsfoss.com/testing-local-llms-without-gpu)
- Qwen3 8B at 4-5 tok/s on an i7-12700 CPU (guide, weak source) — [PromptQuorum](https://www.promptquorum.com/local-llms/best-cpu-only-llm)
- Memory bandwidth is the main CPU bottleneck for generation — [LocalAIMaster](https://localaimaster.com/blog/run-llm-cpu-only)

### Inferences
- Rough RAM: Q4 download size plus 1-2GB overhead. 7b about 6GB, 3b about 3GB. 16GB RAM comfortably runs 7b; 8GB laptops should use 3b.
- Generation time for a ~150-token JSON answer (computed from the cited tok/s ranges, not directly measured): at 5-7 tok/s (7B on CPU) about 20-30 s; at 10-20 tok/s (3B) about 8-15 s; at 25+ tok/s about 6 s. Add prompt processing and cold load.
- For a 5 minute live demo with about 3 LLM nodes (planner, decision, critic) and a possible second pass in Scenario B (about 5-6 calls), 3B models keep the run under about 1-1.5 min; 7B on CPU could take 2-3 min. Keep JSON schemas short (few fields, short reasons) to cut output tokens. Mock mode is the backup.
- Prefer qwen2.5 (non-thinking, strong JSON following per general reputation, not verified here) for this project. qwen3 small sizes could work but add thinking complexity.

### Gaps
- No reliable independent JSON-validity benchmark for these models found. Real-world CPU tok/s for Manc's machine unknown (hardware not given).
- Gemma 4 / other new Oct 2026 models: sizes and quality not researched.

## 4. Pitfalls: cold start, thinking tags, validation, retry

### Takeaway
Pre-warm the model, keep it loaded, disable thinking, constrain with `format` schema, validate with pydantic, retry once, then deterministic fallback.

### Cited Findings
- Default keep-alive is 5 minutes, then the model unloads, so the next call reloads it — [Ollama FAQ](https://docs.ollama.com/faq)
- Thinking is returned in a separate `message.thinking` field when the API's thinking mode is used; `think=False` disables it where allowed — [Ollama thinking docs](https://docs.ollama.com/capabilities/thinking)
- The thinking docs do not say how `think` interacts with `format` — [Ollama thinking docs](https://docs.ollama.com/capabilities/thinking)
- `OLLAMA_NUM_PARALLEL` default 1; memory scales with parallelism times context length — [Ollama FAQ](https://docs.ollama.com/faq)

### Inferences
- Cold load of a 2-5GB model from SSD is typically several seconds to tens of seconds (my estimate, no source). Warm up once at startup with a tiny `chat(..., keep_alive="30m")` call before the demo; use `keep_alive=-1` or `"1h"`.
- Pass `think=False` for qwen3-type models; also strip any `<think>...</think>` with a regex before `json.loads` as a safety net.
- Validate with pydantic (`model_validate_json`) rather than adding jsonschema: fewer dependencies. Use `Literal["DEPLOY","HOLD","BLOCK"]` so wrong enum values fail validation.
- Set a client timeout (`Client(timeout=...)`, kwargs pass to httpx per PyPI page) so a stuck model cannot hang the demo.
- Keep prompts and `num_ctx` small to reduce CPU time.

### Gaps
- Cold-start numbers not found in sources.

## 5. Offline and deterministic runs

### Takeaway
Models run fully offline after `ollama pull`. Set temperature 0 plus a fixed seed; repeat runs on the same machine, version, model digest and settings should usually match, but this is not guaranteed across machines or versions.

### Cited Findings
- To get reproducible output, set both temperature 0 and a fixed seed in `options`, e.g. `{"seed": 101, "temperature": 0}` — [Makandra](https://makandracards.com/makandra/626358-ollama-generate-reproducible-results); [SSD Nodes](https://www.ssdnodes.com/learn/ollama-temperature-and-sampling)
- Output can still differ with: different quantization, Ollama version, GPU/CPU layer split, concurrent requests, different num_ctx or prompt prefix — [SSD Nodes](https://www.ssdnodes.com/learn/ollama-temperature-and-sampling)
- Another engine's docs (llama.cpp wrapper) say temperature 0 is greedy and seed irrelevant — conflicting with the guides above; different engine — [Aspose LLM docs](https://docs.aspose.com/llm/net/developer-reference/parameters/sampler/seed/)
- Anecdote of inconsistent output across Macs with different Ollama versions — [Makandra](https://makandracards.com/makandra/626358-ollama-generate-reproducible-results)

### Inferences
- Outputs are "mostly" reproducible on one machine, not guaranteed. For the demo, do not rely on the real model for correctness: CLAUDE.md's deterministic floor in code (critic rules, `DEMO_SEED_WRONG_DECISION`) plus MockLLM already covers this.
- Pin the model tag and run `ollama --version` check at startup; test by running the same prompt twice and comparing.
- Offline: after pulling, no internet is needed (generally true of Ollama; not explicitly confirmed in fetched docs).

### Gaps
- Not tested in this research; reproducibility claims come from secondary guides.
