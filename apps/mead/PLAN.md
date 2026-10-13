# Mead Log plan

Single-user web app on Tars for tracking past, current and planned mead batches and their chemistry, plus a small recipe library.

**Reference:** the [Modern Meadmaking wiki](https://wiki.meadtools.com/en/home) (the r/mead wiki). Its formulas, rules of thumb and starter recipes are the source of truth, and the app links to the relevant wiki page wherever it gives advice.

## Decisions

| | |
|---|---|
| Location | `tars/apps/mead/` (the `ehulle117/homebrew` repo stays unused) |
| Stack | FastAPI, built-in `sqlite3`, Jinja templates, Chart.js from CDN |
| Readings | Hydrometer, entered by hand (no refractometer, Tilt or iSpindel) |
| Data | Starts empty except for the seeded wiki recipes; no import |
| Units | US (gal, lb, °F); metric weights and volumes convert on entry |
| Access | LAN only, no login, same as the other Tars apps |
| Node | `k3s-worker-case` (amd64); covered by the case-worker appdata backup. Moved off `tars` on 2026-10-13, when `tars` was tainted for disk pressure |

## Checked against the wiki

| Prototype | Wiki says | Result |
|---|---|---|
| Honey = 35 points per lb per gallon | Backsweetening formula uses 0.035/lb/gal; Basic Traditional is 3.2 lb in 1 gal → 1.110 | Matches |
| Fermaid-O ≈ 160 ppm effective YAN per g/L | MeadTools source: 40 ppm/g/L × 4 with GoFerm (× 3 without); wiki example → ≈156 | Matches; add the ×3 no-GoFerm case |
| YAN target = Brix × 10 × factor | MeadTools source: Brix × **SG** × 10 × factor (low 0.75, medium 0.9, high 1.25, very high 1.8); max 2.5 g/L of Fermaid-O | **Change**; 1.100/1 gal/medium → 235 ppm, ≈5.6 g total |
| TOSNA: 4 doses at 24h/48h/72h, then the 1/3 break or day 7 | Same | Matches |
| K-meta is 57.6% SO₂ | 57% free SO₂ | Matches |
| "Stable" = last 3 readings within 0.001 | Stable = two readings **a week apart** that agree | **Change** |
| OG estimate counts only weighed ingredients | Cyser recipe uses 1 gal of apple juice, measured by volume | **Change** |

## Done (prototype, not committed)

- `chem.py` and `test_chem.py` (7 passing tests).
- `main.py` and `templates/`:
  - **Dashboard:** batches grouped by status, with the next action for each.
  - **Batch page:** details, ingredients, readings with a gravity chart, TOSNA checklist, event log, clone and delete.
  - **Calculators page.**

## Remaining work

### 1. Changes to the app from the wiki

**Recipes**
- A recipe is a batch with status `recipe`, so it reuses the same ingredients table and the existing clone action. No new tables.
- The dashboard hides recipes. A **Recipes** page lists them with a **Brew this** button, which clones the recipe into a `planned` batch.
- New batch columns:
  - `target_og`
  - `target_fg_max`, so the wiki's FG ranges (e.g. 1.012–1.022) fit, alongside the existing `target_fg`
  - `source_url`
- `seed.py` inserts these wiki recipes once, when the database is empty:
  - 1 gal: Basic Traditional, Basic Metheglin, Basic Melomel, Basic Cyser
  - 5 gal: Traditional, Chai Metheglin, Cherry Melomel, Standard Cyser, Rhodomel, Blackberry Orange Blossom Melomel, Smoked Capsicumel, Sparkling Hydromel, Bochet, Braggot
  - Seeding adds any recipe not added before, and remembers it, so deleted recipes stay deleted
- What gets stored for each recipe:
  - ingredients, amounts, yeast and target gravities (these are facts)
  - a short method summary in my own words
  - a link to the wiki page

  Method text is **not** copied: the wiki asks that it not be used to reproduce content.
- "Save as recipe" on any batch turns one of your own brews into a recipe.

**Chemistry**
- **Liquid fermentables:** an ingredient measured by volume (gal, L, mL) can have a PPG, read as gravity points per gallon of that liquid (apple juice ≈ 45–50). That makes the cyser estimate correct.
- **Stability check:** use readings at least 7 days apart, as the wiki specifies.
- **Next-action prompts** on the dashboard:
  - "Stable but above target FG": possible stuck fermentation, linking the wiki's stuck-fermentation page.
  - "Stable at target": stabilize or rack.
  - After a `stabilize` event: wait 24 h before backsweetening.
- **Style badge** from the BJCP ranges on the wiki:
  - strength from OG: hydromel 1.035–1.080, standard 1.080–1.120, sack 1.120–1.170
  - sweetness from FG: dry < 1.010, semi-sweet 1.010–1.025, sweet 1.025–1.050
- **Stabilization helper:**
  - K-meta shown in Campden tablets too (1 tablet = 0.44 g)
  - a warning that sorbate is unreliable above about 14% ABV
  - a reminder to confirm stability first
- **Backsweetening helper:** suggests adding ½–¾ of the calculated honey first and stepping up, as the wiki recommends.
- **Nutrient protocol per batch:**
  - `TOSNA` (default; match the MeadTools math, with a GoFerm yes/no checkbox and a "very high" nitrogen option)
  - `as recipe`: the beginner recipes use DAP and boiled bread yeast up front, so no checklist
  - Bray Denard: not now (see "Not doing")

### 2. Finish the app
- `requirements.txt` with pinned versions: fastapi, uvicorn, jinja2, python-multipart.
- Set `TZ=America/New_York` in the container. Without it, a reading entered in the evening would default to tomorrow's (UTC) date.
- Add tests to `test_chem.py`:
  - style classification
  - liquid fermentable OG
  - the 7-day stability rule
  - TOSNA output matches MeadTools for a known case (1.100, 1 gal, medium, with GoFerm)
  - the seeded recipes' estimated OGs land within 0.005 of the wiki's targets (a check that the seed data and the math agree)

### 3. Container
- `Dockerfile`: `python:3.12-alpine`, install the requirements, run `uvicorn main:app --host 0.0.0.0 --port 8770`.
- The database lives at `MEAD_DB=/data/mead.db` on a PVC mounted as a directory.
- Run as uid 1000 with `fsGroup` 1000, like overseerr.

### 4. CI: `.github/workflows/mead.yml`
- Copy `adsb-tools.yml`, with these changes:
  - trigger on `apps/mead/**`
  - build `linux/amd64` only, with no QEMU step
  - run `pytest` before building
- Image: `ghcr.io/ehulle117/tars-mead:main`.
- One manual step: after the first push, make the ghcr package public, as done for `tars-adsb-tools`. The cluster has no pull secret.

### 5. Manifest: `apps/mead.yaml`
- PVC `mead-data-pvc`: 1Gi, `local-path`.
- Deployment `mead`:
  - 1 replica, `Recreate` (SQLite must have only one writer)
  - pinned to the `tars` node
  - readiness probe on `GET /`
  - small resource requests
- Service `mead-svc`: LoadBalancer on port 8770, which no other app uses.
- No Ingress: `*.tars.local` and `*.case.local` resolve to Nginx Proxy Manager (192.168.8.250), which routes `homebrew.case.local` to port 8770.

### 6. Docs and wiring
- Add a row to the services table in `README.md`.
- Optional: a Homarr tile and an Uptime Kuma monitor.

### 7. Roll out
1. Commit to `main` (tars commits straight to main), with your OK before the push.
2. The CI build passes, then make the ghcr package public.
3. Argo CD syncs `apps/mead.yaml`.
4. Check:
   - `kubectl -n apps get pods -l app=mead`
   - open `homebrew.case.local` and see the 14 seeded recipes
   - use "Brew this" to start a batch, then delete the pod and confirm the batch survives the restart
5. Confirm the next 3 AM backup picked up `mead.db`.

## Decided
- Recipes: the four 1-gal beginner recipes plus four 5-gal ones (above).
- Nutrients: TOSNA only.
- Backups: the existing 3 AM appdata backup is enough.

## Not doing (add when needed)
- Login: add it if the app is ever exposed beyond the LAN.
- Hydrometer import (Tilt/iSpindel): add it if you buy one.
- Photos: add them if tasting notes need pictures.
- Carbonation calculator: add it when you brew the Sparkling Hydromel.
- Archive filters: add them once there are enough batches to need them.
- Bray Denard nutrient schedule: add it if you want to try it (a 7-row lookup table, plus potassium carbonate and GoFerm or Fermaid K).
- Syncing recipes from the wiki: recipes are seeded once, and you edit them locally.
