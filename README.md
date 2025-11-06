# Cargo333 — deployment notes

This repository contains the Cargo333 Flask web app.

This README explains how to deploy the app to Render.com in a way that intentionally uses an ephemeral (non-persistent) database so the database will be lost between deploys.

Important note about the database
- The Render manifest (`render.yaml`) is configured to set `DATABASE_URL` to an SQLite file under `/tmp`:
  - `sqlite:////tmp/cargo333.sqlite3`
- On Render, the instance filesystem is ephemeral. Files written to `/tmp` or the container filesystem will be lost when the service is redeployed or the instance restarts. Therefore this configuration makes the database intentionally non-persistent (it will be lost on every deploy or instance replacement).

If you want a persistent database (not recommended per current request), you should instead provide a PostgreSQL database URL via the `DATABASE_URL` environment variable and remove/override the `sqlite` setting.

Quick Render deployment steps
1. Push the repository to a GitHub/GitLab repository.
2. Create a new Web Service on Render and either choose "Connect a repository" or use the `render.yaml` manifest in this repo.
3. The included `render.yaml` contains:
   - `buildCommand: pip install -r requirements.txt`
   - `startCommand: gunicorn app:app`
   - `DATABASE_URL` set to `sqlite:////tmp/cargo333.sqlite3` (ephemeral)
   - `SECRET_KEY` placeholder — set a real secret in Render's dashboard if you want to keep sessions secure across restarts.
4. After the service builds and starts, open the provided URL. The app will create the SQLite DB on first access.

Local testing notes
- Locally you can run with a persistent DB by setting `DATABASE_URL` to a postgres URL or a sqlite file in your project directory. Example for local ephemeral testing (in bash):

```bash
export DATABASE_URL="sqlite:///./dev-data.sqlite3"
export FLASK_ENV=development
python app.py
```

Security & production notes
- Using an ephemeral SQLite DB means all application data is lost on redeploys. This is useful for demos or throwaway environments but not for production usage.
- If you want persistent data, use a managed Postgres instance and set `DATABASE_URL` in Render to that Postgres URL.
- For production, set a secure `SECRET_KEY` in Render's environment variables (do not commit it to source control).

Files changed for Render readiness
- `render.yaml`: updated with `DATABASE_URL` env var pointing to an ephemeral SQLite file and a `SECRET_KEY` placeholder.
- `wsgi.py`: fixed missing `os` import.

If you want, I can:
- Add a `Procfile` and a small `render` directory for more advanced deployment options.
- Switch the default in `render.yaml` to a Postgres database and show exact Render-managed Postgres setup steps (if you prefer persistent data).
- Add a health-check endpoint that returns 200 (if you want a lightweight health endpoint separate from `/`).


