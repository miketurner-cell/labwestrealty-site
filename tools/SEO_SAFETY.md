# SEO safety check

Added 2026-10-11 (sites, D-1011-21 item 1). Stops a change from quietly costing a search page what it had.

**What it checks.** For every page in `tools/seo-pages.json`, the page as it was at the base commit against the same page now: `<title>`, meta description, canonical, index status (a new noindex meta, `X-Robots-Tag` in `netlify.toml`/`_headers`, or a `robots.txt` Disallow), its entry in any `sitemap*.xml`, and the link to it from the homepage/nav. A loss in any of these is a LOSS. A rewritten title or description is only a note, and a page that now 301s (`_redirects`) is a note. A page that did not exist at base has no baseline and is skipped.

**Run it locally** (offline, stdlib Python, no browser, no GSC):

    python3 tools/seo-safety-check.py --base origin/main          # your working tree against main
    python3 tools/seo-safety-check.py --base <sha>^ --head <sha>  # a past commit
    python3 tools/tests/seo-safety-check-test.py                  # proves every kind of loss is caught

**Mode.** `"mode"` in `tools/seo-pages.json`: `warn` (ships this way; LOSS lines print as CI warnings, exit 0) or `fail` (exit 1). Flipping to `fail` is a one-line PR that Mike names.

**The page list.** `python3 tools/seo-pages-refresh.py` rebuilds it from `sitemap.xml`, the pages named in `_research/digests/*.md`, and `tools/seo-cache/gsc-pages.json` when the weekly SEO digest writes it (GSC credentials stay a GitHub secret, never in PR CI). Add a page by hand with `"pinned": true`. In CI nothing refreshes it, so a stale list only means newer pages are not covered yet.
