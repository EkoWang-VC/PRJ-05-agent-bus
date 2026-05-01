PYTHON ?= python3
SMOKE_REPORT ?= /tmp/agent-bus-queue-sync-smoke.md
AGENT ?=
REQUEST ?=
OUTPUT_ROOT ?= .
RESPONSE_OUT ?= /tmp/agent-bus-cli-smoke-$(AGENT).json
TIMEOUT ?= 45
MODEL ?=
EXTRA_ARGS ?=

.PHONY: test smoke smoke-cli

test:
	$(PYTHON) -m unittest discover -s tests -q

smoke: test
	$(PYTHON) scripts/queue_sync.py --requests-dir requests --responses-dir responses --out $(SMOKE_REPORT)
	@printf 'smoke_report=%s\n' "$(SMOKE_REPORT)"

smoke-cli:
	@test -n "$(AGENT)" || (echo "AGENT is required: claude | claude-ds | codex | gemini" && exit 1)
	@test -n "$(REQUEST)" || (echo "REQUEST is required: e.g. REQUEST=requests/REQ-XXX.json" && exit 1)
	@case "$(AGENT)" in \
		claude) script="scripts/claude_worker.py" ;; \
		claude-ds) script="scripts/claude_ds_worker.py" ;; \
		codex) script="scripts/codex_worker.py" ;; \
		gemini) script="scripts/gemini_worker.py" ;; \
		*) echo "Unsupported AGENT: $(AGENT)" && exit 1 ;; \
	esac; \
	set -- "$(PYTHON)" "$$script" "$(REQUEST)" --output-root "$(OUTPUT_ROOT)" --out "$(RESPONSE_OUT)" --invoke-cli --preflight --timeout-seconds "$(TIMEOUT)"; \
	if [ -n "$(MODEL)" ]; then set -- "$$@" --model "$(MODEL)"; fi; \
	if [ -n "$(EXTRA_ARGS)" ]; then set -- "$$@" $(EXTRA_ARGS); fi; \
	"$$@"; \
	printf 'smoke_cli_response=%s\n' "$(RESPONSE_OUT)"
