---
kind: external_dependency
name: MongoDB — persistent store for interviews, candidates, brain state
slug: mongodb
category: external_dependency
category_hints:
    - vendor_identity
scope:
    - '**'
source_files:
    - services/backend-api/db/mongo.py
    - services/backend-api/requirements.txt
---

### Role

### Usage
- Local laptop deployment runs MongoDB on port 27017 (configured per laptop `.env`).
- Stage 1 has an explicit fallback when Mongo is intermittently down (documented in Phase 0 status).