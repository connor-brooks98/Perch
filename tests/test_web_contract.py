from pathlib import Path
from html.parser import HTMLParser
import json
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def run_javascript(source: str):
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", source],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


class BrandTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_brand = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = attributes.get("class", "").split()
        if tag == "a" and "brand" in classes:
            self.in_brand = True

    def handle_endtag(self, tag):
        if tag == "a" and self.in_brand:
            self.in_brand = False

    def handle_data(self, data):
        if self.in_brand:
            self.parts.append(data)

    @property
    def text(self):
        return " ".join(" ".join(self.parts).split())


class WebContractTests(unittest.TestCase):
    def test_shell_uses_perch_identity_and_semantic_navigation(self):
        html = read("web/site/index.html")
        parser = BrandTextParser()
        parser.feed(html)
        self.assertEqual(parser.text, "Perch · Sara's Feeder")
        self.assertIn('href="#/today"', html)
        self.assertIn('href="#/birds"', html)
        self.assertIn('href="#/favorites"', html)
        self.assertIn('id="view"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn('<script type="module" src="app.js"></script>', html)

    def test_frontend_never_reads_legacy_static_json(self):
        scripts = "\n".join(
            path.read_text() for path in (ROOT / "web/site").rglob("*.js")
        )
        self.assertNotIn("detections.json", scripts)
        self.assertIn('"/api/today"', scripts)

    def test_shell_does_not_load_remote_google_fonts(self):
        html = read("web/site/index.html")
        self.assertNotIn("fonts.googleapis.com", html)
        self.assertNotIn("fonts.gstatic.com", html)

    def test_shell_brand_mark_exists(self):
        self.assertTrue((ROOT / "web/site/icons/perch-mark.svg").is_file())

    def test_service_worker_caches_the_complete_perch_module_shell(self):
        source = read("web/site/sw.js")
        match = re.search(r"const SHELL = (\[[^;]+\]);", source)
        self.assertIsNotNone(match)
        shell = set(json.loads(match.group(1)))
        modules = {
            path.name
            for path in (ROOT / "web/site").glob("*.js")
            if path.name != "sw.js"
        }
        required = {
            "./",
            "index.html",
            "styles.css",
            "manifest.json",
            "icons/perch-mark.svg",
            "icons/apple-touch-icon.png",
            "icons/icon-192.png",
            "icons/icon-512.png",
        }
        self.assertLessEqual(modules | required, shell)
        self.assertIn('const CACHE = "perch-shell-v1"', source)
        self.assertNotIn("fieldlog-v1", source)
        self.assertIn('url.pathname.includes("/data/")', source)
        self.assertIn('url.pathname.includes("/thumbs/")', source)

    def test_api_client_builds_endpoints_and_uses_one_request_policy(self):
        result = run_javascript(
            """
            const calls = [];
            globalThis.fetch = async (...args) => {
              calls.push(args);
              return {ok: true, json: async () => ({ok: true})};
            };
            const api = await import('./web/site/api.js');
            await api.getToday();
            await api.getDetections({limit: 12, favorite: true});
            await api.getDetection(42);
            await api.patchDetection(42, {favorite: true});
            await api.getSpecies({q: 'blue jay', sort: 'recent'});
            await api.getSpeciesDetail('sci:Blue jay', {limit: 3});
            await api.searchTaxa('great horned');
            console.log(JSON.stringify(calls));
            """
        )
        self.assertEqual(
            [call[0] for call in result],
            [
                "/api/today",
                "/api/detections?limit=12&favorite=true",
                "/api/detections/42",
                "/api/detections/42",
                "/api/species?q=blue+jay&sort=recent",
                "/api/species/sci%3ABlue%20jay?limit=3",
                "/api/taxa?q=great+horned",
            ],
        )
        for _, options in result:
            self.assertEqual(options["cache"], "no-store")
            self.assertEqual(options["headers"], {"Content-Type": "application/json"})
        self.assertEqual(result[3][1]["method"], "PATCH")
        self.assertEqual(result[3][1]["body"], '{"favorite":true}')

    def test_api_client_surfaces_server_errors(self):
        result = run_javascript(
            """
            globalThis.fetch = async () => ({
              ok: false,
              status: 503,
              json: async () => ({message: 'Still waking up', code: 'offline'}),
            });
            const {getToday} = await import('./web/site/api.js');
            try { await getToday(); } catch (error) {
              console.log(JSON.stringify({message: error.message, status: error.status, body: error.body}));
            }
            """
        )
        self.assertEqual(result["message"], "Still waking up")
        self.assertEqual(result["status"], 503)
        self.assertEqual(result["body"]["code"], "offline")

    def test_router_recognizes_routes_and_normalizes_unknown_hashes(self):
        result = run_javascript(
            """
            const {parseRoute} = await import('./web/site/router.js');
            const hashes = [
              '#/today', '#/history?date=2026-07-14', '#/birds', '#/favorites',
              '#/species/sci%3Ablue%20jay?limit=3', '#/visits/42', '', '#/nope'
            ];
            console.log(JSON.stringify(hashes.map((hash) => {
              const route = parseRoute(hash);
              return {name: route.name, params: Object.fromEntries(route.params)};
            })));
            """
        )
        self.assertEqual(
            result,
            [
                {"name": "today", "params": {}},
                {"name": "history", "params": {"date": "2026-07-14"}},
                {"name": "birds", "params": {}},
                {"name": "favorites", "params": {}},
                {"name": "species", "params": {"key": "sci:blue jay", "limit": "3"}},
                {"name": "visit", "params": {"id": "42"}},
                {"name": "today", "params": {}},
                {"name": "today", "params": {}},
            ],
        )

    def test_router_treats_malformed_encoded_paths_as_unknown(self):
        result = run_javascript(
            """
            const {parseRoute} = await import('./web/site/router.js');
            const route = parseRoute('#/species/%E0%A4%A');
            console.log(JSON.stringify({name: route.name, params: Object.fromEntries(route.params)}));
            """
        )
        self.assertEqual(result, {"name": "today", "params": {}})

    def test_router_renders_immediately_tracks_hash_changes_and_cleans_up(self):
        result = run_javascript(
            """
            const listeners = new Map();
            globalThis.window = {
              location: {hash: '#/birds'},
              addEventListener(name, callback) { listeners.set(name, callback); },
              removeEventListener(name, callback) {
                if (listeners.get(name) === callback) listeners.delete(name);
              },
            };
            const {startRouter} = await import('./web/site/router.js');
            const rendered = [];
            const cleanup = startRouter((route) => rendered.push(route.name));
            window.location.hash = '#/favorites';
            listeners.get('hashchange')();
            cleanup();
            console.log(JSON.stringify({rendered, listening: listeners.has('hashchange')}));
            """
        )
        self.assertEqual(result, {"rendered": ["birds", "favorites"], "listening": False})

    def test_app_bootstraps_the_router_without_implementing_views(self):
        app = read("web/site/app.js")
        self.assertIn('from "./router.js"', app)
        self.assertIn("startRouter", app)
        self.assertIn("route.name", app)

    def test_format_module_exposes_shared_journal_formatters(self):
        result = run_javascript(
            """
            const format = await import('./web/site/format.js');
            console.log(JSON.stringify({
              confidence: format.formatConfidence(0.876),
              visits: format.formatVisitCount(1),
              visitsMany: format.formatVisitCount(3),
              missingTime: format.formatRelativeTime(null),
            }));
            """
        )
        self.assertEqual(
            result,
            {
                "confidence": "88%",
                "visits": "1 visit",
                "visitsMany": "3 visits",
                "missingTime": "",
            },
        )


if __name__ == "__main__":
    unittest.main()
