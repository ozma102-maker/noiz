NOIZ stable manual-only restore

This package is for the stable repository only.

Before/while applying it to the stable repo, DELETE these if they exist:
- .github/
- scripts/
- requirements.txt
- data/event-inventory.json
- data/noiz-draft-review.json
- data/noiz-curation-seed.json
- data/noiz-seed-stable.json
- data/noiz-grouping-debug.json

Do not run GitHub Actions on the stable repository.

Stable should be updated manually by replacing only:
- data/noiz-data.json
- data/art-noiz-data.json when needed
