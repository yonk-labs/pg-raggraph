# Intentionally empty

The upstream Dockerfile this image is lifted from (`yonk-samples/graphrag-demo/postgres/Dockerfile`) ends with:

    COPY initdb/ /docker-entrypoint-initdb.d/

which copies any `.sql` files in this directory into PostgreSQL's init hooks. In the bake-off we deliberately leave this directory empty because both engine adapters (`src/age_bakeoff/engines/pgrg.py` and `src/age_bakeoff/engines/age.py`) bootstrap their own schemas at ingest time. Keeping this directory empty preserves byte-identical parity with the upstream Dockerfile without running demo init SQL.

Do not add `.sql` files here unless you want them executed on every fresh AGE container boot.
