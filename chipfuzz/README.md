# ChipFuzzer Static Web UI

This directory contains the static frontend used to display ChipFuzzer runtime status, logs, coverage statistics, and workflow progress.

## Files

- `index.html`: main page.
- `assets/style.css`: page styling.
- `assets/main.js`: log streaming, statistics, and coverage charts.
- `assets/workflow.js`: workflow visualization logic.

## Open Locally

You can open `index.html` directly in a browser.

For a local static server:

```powershell
python -m http.server 5173
```

Then visit:

```text
http://localhost:5173/
```

## Connecting to the Backend

Start the Web API from `chipfuzz/server/`, then set the API base URL in the UI. The frontend can read logs through polling or SSE depending on the backend configuration.

## Customization

Replace placeholder links, paths, and screenshots in `index.html` and `assets/` with the artifact-specific values used in your environment.
