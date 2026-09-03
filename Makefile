# Synthetic data only. Nothing here touches a real patient record.
COMPOSE := docker compose -f docker/docker-compose.yml
FHIR_URL ?= http://localhost:8080/fhir
PATIENTS ?= 200
SEED ?= 20260902
PY ?= .venv/bin/python

.PHONY: fhir-up fhir-down fhir-check synthea synthea-jar load clean-fhir readme-check fixture-load ci-fixture conversations eval smoke replay loadtest verify

fhir-up:  ## Bring up HAPI FHIR + Postgres and wait for the capability statement
	$(COMPOSE) up -d
	@echo "waiting for HAPI to answer /metadata ..."
	@for i in $$(seq 1 90); do \
	  curl -sf $(FHIR_URL)/metadata > /dev/null && echo "HAPI ready after $${i}0s" && exit 0; \
	  sleep 10; \
	done; echo "HAPI did not become ready"; $(COMPOSE) logs --tail 40 fhir; exit 1

fhir-down:
	$(COMPOSE) down

clean-fhir:  ## Destroys the synthetic database volume
	$(COMPOSE) down -v

synthea: tools/synthea-with-dependencies.jar  ## Generate synthetic FHIR R4 bundles. Runs Synthea in a JDK container; no host JRE needed.
	@# make only checks that the jar exists. A download interrupted halfway leaves a
	@# file that exists and is unusable, and the failure surfaces as an unhelpful
	@# "Unable to access jarfile". Validate it here, before the container starts.
	@python3 -c "import zipfile,sys;\
	  sys.exit(0) if zipfile.is_zipfile('tools/synthea-with-dependencies.jar') else sys.exit(1)" \
	  || { echo "tools/synthea-with-dependencies.jar is truncated or corrupt; rm it and rerun"; exit 1; }
	mkdir -p data/synthea
	docker run --rm -v "$(PWD)/tools:/tools" -v "$(PWD)/data/synthea:/out" \
	  eclipse-temurin:21-jre java -jar /tools/synthea-with-dependencies.jar \
	  -p $(PATIENTS) -s $(SEED) -cs $(SEED) --exporter.baseDirectory /out \
	  --exporter.fhir.export true --exporter.hospital.fhir.export false \
	  --exporter.practitioner.fhir.export false --generate.log_patients.detail none
	@echo "bundles: $$(ls data/synthea/fhir/*.json 2>/dev/null | wc -l)"

synthea-jar: tools/synthea-with-dependencies.jar  ## Fetch the Synthea jar (188 MB)

tools/synthea-with-dependencies.jar:
	mkdir -p tools
	@# Download to a temp name and move only on success, so an interrupted download
	@# never leaves something at the real path that make will treat as done.
	curl -sSL -C - --retry 5 --retry-delay 3 -o $@.part \
	  https://github.com/synthetichealth/synthea/releases/download/master-branch-latest/synthea-with-dependencies.jar
	@python3 -c "import zipfile,sys;\
	  sys.exit(0) if zipfile.is_zipfile('$@.part') else sys.exit(1)" \
	  || { echo "downloaded jar is not a valid archive"; rm -f $@.part; exit 1; }
	mv $@.part $@
	@echo "  jar verified"

load:  ## Load the generated bundles into HAPI. Refuses to load on top of existing data.
	$(PY) scripts/load_synthea.py --fhir-url $(FHIR_URL) --bundle-dir data/synthea/fhir

fhir-check:  ## Assert the loaded dataset looks the way the agent expects
	$(PY) scripts/fhir_check.py --fhir-url $(FHIR_URL)

fixture-load:  ## Load the small committed fixture (10 patients). No 188 MB download.
	@curl -sf -X POST $(FHIR_URL) -H 'Content-Type: application/fhir+json' \
	  --data-binary @data/ci-fixture/bundle.json -o /tmp/fixture-load.json \
	  -w "  HTTP %{http_code}\n"
	@$(PY) -c "import json,collections; d=json.load(open('/tmp/fixture-load.json')); \
	  print('  created:', dict(collections.Counter(e.get('response',{}).get('status','?') \
	  for e in d.get('entry',[]))))"

ci-fixture:  ## Rebuild data/ci-fixture/bundle.json from a full Synthea run
	PYTHONPATH=src $(PY) scripts/make_ci_fixture.py

conversations:  ## Regenerate the conversation set from whatever is loaded in FHIR
	PYTHONPATH=src $(PY) scripts/generate_conversations.py --fhir-url $(FHIR_URL) --count 200

eval:  ## Full rubric run with per-guard mutation
	PYTHONPATH=src $(PY) -m eval.conversation_run

smoke:  ## 20-turn pre-traffic replay
	PYTHONPATH=src $(PY) -m eval.replay --smoke 20

replay:  ## Full replay against the committed baseline; blocks on regression
	PYTHONPATH=src $(PY) -m eval.replay

loadtest:  ## 2,000 concurrent sessions plus the injected-fault detector proof
	PYTHONPATH=src $(PY) -m eval.loadtest --sessions 2000 --concurrency 250

verify:  ## Everything a deploy must pass
	PYTHONPATH=src $(PY) scripts/phi_lint.py
	PYTHONPATH=src $(PY) -m pytest -q
	$(MAKE) fhir-check
	$(MAKE) smoke
	$(MAKE) replay

readme-check:  ## Regenerate every number in the README and diff it
	PYTHONPATH=src $(PY) scripts/readme_check.py
