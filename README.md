# boatconnect

Share a boat, share the calendar. People who use a boat together keep track of who has it when: find a boat, ask to join as an **owner** or as **crew**, and see every trip on
a month calendar like Google Calendar's.

- **Boats** are public to browse. A new boat waits for the site administrator's approval.
- **Joining**: anyone registered can ask. The administrator approves **owners** (who hold a share of the boat, which can be a fraction); a boat's owners approve its **crew**.
- **Shares over time**: owners' shares may add up to at most 100%. An owner can lower their own share (or raise it into room nobody holds); that makes room for a new owner,
  who is then approved as usual. Every change is kept in the boat's share history, which its members can read.
- **Editing**: only an owner can change a boat's name, port, description and time zone.
- **Leaving**: a member can leave; an owner can remove crew; an owner leaves only by their own choice (the administrator can also remove anyone). A boat keeps at least one owner.
- **Trips**: an owner books the boat with a start and an end time. Crew and other owners **sign on** to a trip, and any number can be aboard. Two trips of one boat may not
  overlap. A trip may have a limit on how many can come.
- The calendar is shown in the boat's own time zone; the server stores UTC.
- Only a boat's members see its calendar and who belongs to it.

The page background is a photograph at 30% strength: `--background-opacity` in `web/src/styles.css`.

## Run it

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
(cd web && npm install && npm run build)
DATA_DIR=/tmp/bc-data ADMIN_EMAILS=admin@example.com .venv/bin/uvicorn boatconnect.server:app --port 8001
.venv/bin/python scripts/seed-demo.py          # optional: sample people, boats and trips
```

Open http://127.0.0.1:8001. For front-end work, `cd web && npm run dev` serves on :5173 and forwards `/api` to :8001.

## Test it

```sh
.venv/bin/python -m pytest        # the store and every API rule
(cd web && npm test)              # the calendar arithmetic (months, time zones, bars)
```

## Settings

See `.env.example`: `DATA_DIR`, `ADMIN_EMAILS`, `COOKIE_SECURE`.
