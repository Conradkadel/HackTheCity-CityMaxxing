# Sharing the database

The development database is approximately 51 GB. Do not add a dump to Git history: GitHub blocks normal repository files above 100 MiB, and cloning a repository containing database binaries is inefficient.

The verified `all-carris` export from this dataset is 4.25 GB as a temporary PostgreSQL database and **576 MB** as a custom-format archive. Size can change when the source dataset changes.

## Recommended CARRIS archive

Build the privacy-safe portable database and compressed PostgreSQL archive with:

```sh
./scripts/export_carris_database.sh
```

The default `all-carris` mode contains:

- all observations for event agency `IA9T6` across the active dataset;
- every observed CARRIS area and route, preserving useful surrounding-route context;
- the CARRIS operation plan, route/trip lookup, shapes, stops, and scheduled stop visits;
- rebuilt date/area/operator availability metadata;
- the active dataset metadata needed by the API.

Driver IDs are replaced with `redacted`. Raw `event_sources`, unrelated operators, unrelated plan packages, import-file history, and duplicate raw `stop_times` JSON are omitted. Normalised scheduled-stop rows remain available, so the unified viewer retains its route and schedule functionality.

The output is written to `exports/headway-carris-all-carris.dump`, with a sibling SHA-256 checksum file. Both are ignored by Git.

Two smaller modes are available:

```sh
./scripts/export_carris_database.sh configured-lines
./scripts/export_carris_database.sh challenge-areas
```

`configured-lines` retains exact matched observations for the configured Challenge 7 public lines across all CARRIS areas. `challenge-areas` retains all CARRIS routes, including context and unresolved trips, but only inside the five parent cells of the precise Challenge 7 zones.

## Restore on a colleague's machine

After cloning the repository, the colleague copies the `.dump` file into any local directory, creates `.env` from `.env.example`, and runs:

```sh
npm ci
./scripts/restore_database.sh /path/to/headway-carris-all-carris.dump --replace
npm run dev
```

`--replace` is required because restore deliberately replaces the local Compose database named `headway`. It does not touch another PostgreSQL installation. After restore, the API detects the reduced database and the interface marks omitted operators or lines unavailable instead of failing.

Verify the downloaded archive before restoring:

```sh
cd /directory/containing/the/archive
shasum -a 256 -c headway-carris-all-carris.dump.sha256
```

## Full database archive

If a complete internal backup is genuinely required, create a PostgreSQL custom-format dump:

```sh
mkdir -p exports
docker compose exec -T db pg_dump -U headway -d headway \
  --format=custom --compress=9 --no-owner --no-acl \
  > exports/headway-full.dump
shasum -a 256 exports/headway-full.dump > exports/headway-full.dump.sha256
```

The full archive includes raw provenance and driver identifiers and must be treated as sensitive. Prefer the redacted CARRIS archive for collaboration.

## Upload location

Do not commit either dump. A private GitHub Release can hold up to 2 GiB per release asset; split a larger archive or use approved cloud/object storage. Anyone downloading a private release must have access to the private repository.
