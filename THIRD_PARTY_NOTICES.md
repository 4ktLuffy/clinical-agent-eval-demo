# Third-party notices

This repository redistributes none of the components below. Each is pulled at build time
by `make` or `pip` from its own upstream. What follows is what was verified from the
artifacts themselves on 2026-09-03, with the command used, rather than recalled.

## HAPI FHIR JPA server — Apache-2.0

```
$ docker image inspect hapiproject/hapi:latest --format '{{json .Config.Labels}}'
org.opencontainers.image.licenses = Apache-2.0
org.opencontainers.image.source   = https://github.com/hapifhir/hapi-fhir-jpaserver-starter
org.opencontainers.image.title    = hapi-fhir-jpaserver-starter
org.opencontainers.image.version  = v8.12.0-1
```

Pulled by `make fhir-up`. Not vendored, not modified.

## Synthea — licence not determinable from the distributed artifact

`synthea-with-dependencies.jar` is a shaded fat jar. Inspecting it shows several bundled
licences rather than one:

```
$ python3 -c "import zipfile; z=zipfile.ZipFile('tools/synthea-with-dependencies.jar'); ..."
  x2   Apache License
  x1   GNU LESSER GENERAL PUBLIC LICENSE   (LICENSE.txt, top level)
  x1   Apache Commons CSV      (META-INF/NOTICE.txt)
  x1   # Jackson JSON processor
  x1   Copyright (c) 2018 Oracle and/or its affiliates
```

The top-level `LICENSE.txt` is LGPL-3.0 and belongs to one of the bundled dependencies;
the jar carries no Synthea pom, so **Synthea's own licence cannot be read off this
artifact** and is deliberately not asserted here. Read it from the Synthea repository
before doing anything that depends on it.

This matters less than it looks for this repo, because:

- the jar is gitignored and appears in no commit (verified: the largest blob in the whole
  history across all branches is 464 KB, `data/conversations.json`);
- it is downloaded by `make synthea-jar` at build time and run inside a container;
- nothing in this repository links against it, and no Synthea source is copied in.

It would matter a great deal if this were ever packaged for distribution. Flagged rather
than resolved: resolving it needs a licence decision, not a code change.

## PostgreSQL — PostgreSQL Licence

`postgres:16-alpine` carries no `org.opencontainers.image.licenses` label, so this is
taken from the project rather than the artifact and should be treated as unverified here.
Pulled by `make fhir-up`.

## Eclipse Temurin JRE

`eclipse-temurin:21-jre` is used only as a throwaway container to run the Synthea jar in
`make synthea`. OpenJDK builds are distributed under GPLv2 with the Classpath Exception;
again, taken from the project, not verified from a label on the image.

## Python dependencies

Declared and upper-bounded in `pyproject.toml`: `mcp>=1.9,<3` (MIT),
`anthropic>=0.40,<1.0` (MIT, optional, real-model path only), `pytest>=8.0,<10.0` (MIT,
dev only).

## This repository

MIT, see `LICENSE`.
