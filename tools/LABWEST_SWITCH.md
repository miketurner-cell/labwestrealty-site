# LABWEST_LISTINGS — the Lab West listings switch (D-1012-34)

Repo variable `LABWEST_LISTINGS`: `off` | `preview` | `on`. Unset or anything else = off.
Owner: sites. The flip is Mike's, by name and value. Read it live before any change:
`gh variable list --repo miketurner-cell/labwestrealty-site`.

Rules every Lab West workflow follows (enforced by `tools/tests/labwest-switch-test.py`):
1. First job is `switch` on `ubuntu-latest` (Lab West has no self-hosted runner) and prints the value.
2. Every other job `needs: switch` and gates on `needs.switch.outputs.state` before any RETS login
   (NLAR allows one login per account; a puller running while off would break the other sites).
3. Generated listing, sold and market pages are linked and listed in the sitemap only after the flip.

Also register the gate in `realestategander-site/tools/gates.json` (name, default off, workflow, reader).
Runtime readers (`chat.ts`, `sold-data.ts`) will also read `public.gates` row `site='labwest'`; flip both together.
