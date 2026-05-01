PYTHON ?= python3
SMOKE_REPORT ?= /tmp/agent-bus-queue-sync-smoke.md

.PHONY: test smoke

test:
	$(PYTHON) -m unittest discover -s tests -q

smoke: test
	$(PYTHON) scripts/queue_sync.py --requests-dir requests --responses-dir responses --out $(SMOKE_REPORT)
	@printf 'smoke_report=%s\n' "$(SMOKE_REPORT)"
