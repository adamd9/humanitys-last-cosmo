#!/usr/bin/env bash
# Build two static bundles for Cloudflare Pages from web/ — one repo, two Pages
# projects. Configure each Pages project with:
#   Build command:  bash scripts/build-pages.sh
#   Output dir:     dist/app        (for app.<domain>  — the main SPA + admin)
#                   dist/rankings   (for rankings.<domain> — the public rankings)
#
# The frontend calls the API on Azure (thelastquiz.drop37.com) via the
# host-derived window.API_BASE in static/site-links.js, so these bundles are
# fully static and need no backend of their own.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
web="$root/web"
dist="$root/dist"

rm -rf "$dist"
mkdir -p "$dist/app" "$dist/rankings"

# Shared static assets (JS/CSS/images) go into both bundles.
cp -R "$web/static" "$dist/app/static"
cp -R "$web/static" "$dist/rankings/static"

# The favicon source SVGs and build script under static/favicons are dev-only.
rm -rf "$dist/app/static/favicons" "$dist/rankings/static/favicons"

# --- App SPA (app.<domain>) ---
# No _redirects file on purpose. Cloudflare Pages' native routing already does
# exactly what we need, and a hand-rolled _redirects here caused an
# ERR_TOO_MANY_REDIRECTS loop on /admin:
#   * Pages serves admin.html at the clean URL /admin and 308-redirects
#     /admin.html -> /admin. An explicit "/admin /admin.html 200" proxy fought
#     that auto-redirect (/admin -> /admin.html -> 308 /admin -> ... forever).
#   * A "/* /index.html 200" SPA proxy self-loops too (Pages strips /index -> /
#     -> matches /* again); modern wrangler flags it as an infinite loop.
# Instead we rely on Pages' documented defaults: route matching serves
# admin.html at /admin and real assets at /static/*, while the built-in SPA
# fallback (active because there is no top-level 404.html) serves index.html for
# unmatched client routes (/create-run, /run/<id>, ...).
cp "$web/index.html" "$dist/app/index.html"
cp "$web/admin.html" "$dist/app/admin.html"
cp "$web/favicon.ico" "$dist/app/favicon.ico"

# --- Public site (rankings.<domain> / apex): home.html IS the root ---
# home.html is served at /, and rankings.html is served at the clean URL
# /rankings (Cloudflare Pages serves a file named rankings.html at /rankings,
# exactly like admin.html at /admin). No _redirects file: rankings.json is a
# real asset and Pages' built-in SPA fallback (no 404.html) covers unknown paths.
cp "$web/home.html" "$dist/rankings/index.html"
cp "$web/rankings.html" "$dist/rankings/rankings.html"

# SEO content pages: the guides hub, the blog hub + posts, and long-form articles,
# served at clean URLs (e.g. /dark-triad-ai) exactly like rankings.html at /rankings.
for f in guides blog dark-triad-ai big-five-ai mbti-ai ai-deception-experiment ai-deception-rankings \
         chatgpt-psychosis is-chatgpt-a-psychopath is-ai-personality-real \
         ai-self-preservation which-ai-lies-most ai-lies-to-protect-you; do
  cp "$web/$f.html" "$dist/rankings/$f.html"
done
# DRIP QUEUE — these articles are written & committed but held back (not built, not linked,
# not in the sitemap). On each publish date: add the slug to the loop above, un-comment its
# <url> in web/sitemap.xml and its card in web/blog.html, wire a cross-link or two from the
# live articles, and repoint any links in the new article that still target a not-yet-live slug.
#   2026-08-15  uncensored-ai-models
#   2026-08-22  ai-safety-scorecard
#   2026-08-29  why-ai-sounds-the-same
#   2026-09-05  dark-ai-infrastructure
#   2026-09-12  home-robots-personality
#   2026-09-19  ai-personality-by-country

# Crawl files for the public site (robots + sitemap point at the apex).
cp "$web/robots.txt" "$dist/rankings/robots.txt"
cp "$web/sitemap.xml" "$dist/rankings/sitemap.xml"
cp "$web/favicon.ico" "$dist/rankings/favicon.ico"

# Snapshot the rankings into the bundle so the public page is served entirely
# from Cloudflare's CDN (no backend call per visit). Refreshed on every deploy;
# the page falls back to the live API if this snapshot is missing.
api="${RANKINGS_API_BASE:-https://thelastquiz.drop37.com}"
if curl -fsS --max-time 25 "$api/api/rankings" -o "$dist/rankings/rankings.json"; then
  echo "  snapshot: dist/rankings/rankings.json ($(wc -c <"$dist/rankings/rankings.json" | tr -d ' ') bytes)"
else
  rm -f "$dist/rankings/rankings.json"
  echo "  snapshot: WARNING could not reach $api/api/rankings; page will use the live API"
fi

# Deception experiment snapshot (separate dataset, powers ai-deception-rankings).
if curl -fsS --max-time 25 "$api/api/experiments/rankings" -o "$dist/rankings/deception.json"; then
  echo "  snapshot: dist/rankings/deception.json ($(wc -c <"$dist/rankings/deception.json" | tr -d ' ') bytes)"
else
  rm -f "$dist/rankings/deception.json"
  echo "  snapshot: WARNING could not reach $api/api/experiments/rankings; page will use the live API"
fi

# Cache policy for the snapshot: browsers cache briefly then revalidate against
# the CDN (never the backend); new deploys purge the edge cache so data updates.
cat > "$dist/rankings/_headers" <<'EOF'
/rankings.json
  Cache-Control: public, max-age=60, stale-while-revalidate=86400
/deception.json
  Cache-Control: public, max-age=60, stale-while-revalidate=86400
EOF

# Optional favicon passthrough.
for d in "$dist/app" "$dist/rankings"; do
  [ -f "$web/favicon.ico" ] && cp "$web/favicon.ico" "$d/favicon.ico" || true
done

echo "Built:"
echo "  $dist/app       (app.<domain>)"
echo "  $dist/rankings  (rankings.<domain>)"
