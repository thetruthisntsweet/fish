# Generated types

TypeScript types generated from the Python message models in
`packages/fish-server/src/fish_server/protocol.py`, via the JSON Schemas in `schemas/`.

Never edit files here by hand. After changing a message in Python, run
`scripts/gen_types.sh` and commit the result. `scripts/check.sh` (and CI) fails if these
files differ from what the models produce.