# Karkinos Scripts

Run commands from the repository root.

## Start

Run the stable `main` branch:

```bash
./scripts/start_server.sh
```

Equivalent to:

```bash
./scripts/start_server.sh main
```

Run the current `dev` working tree:

```bash
./scripts/start_server.sh dev
```

Run another locally available branch:

```bash
./scripts/start_server.sh <branch>
```

Behavior:

* `main` runs the locally available `origin/main`, falling back to local `main`.
* `dev` runs the current `dev` working tree, including uncommitted changes.
* Other branches run from managed Git worktrees.
* The launcher never switches the current checkout.
* The launcher never runs `git fetch`.
* Only one Karkinos source runtime may run at a time.

Refresh a remote branch explicitly when needed:

```bash
git fetch origin
./scripts/start_server.sh main
```

`main` uses the repository-local stable configuration and data.

`dev` and other non-`main` branches use development state under:

```text
~/.karkinos/development/
```

Development runs the Web UI with Vite HMR and the backend with reload:

```text
Web: http://127.0.0.1:5173
API: http://127.0.0.1:8000
```

Stable `main` serves the built Web application and API from:

```text
http://127.0.0.1:8000
```

## Stop

Stop the currently running Karkinos source runtime:

```bash
./scripts/stop_server.sh
```

`stop_server.sh` takes no arguments; it stops the currently managed runtime
regardless of which branch started it.

The stop script only stops processes owned by the launcher and does not
terminate unrelated processes based on port usage. It verifies the recorded
process identity before signaling the runtime PID.

## Dependencies

Install Python dependencies:

```bash
uv sync --locked --extra server --extra dev
```

Install frontend dependencies:

```bash
npm ci --prefix web
```

Specialized tooling is grouped under `broker/`, `ci/`, `data/`, `release/`, and `service/`.
