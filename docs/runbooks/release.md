# Runbook: releasing fish-rules, fish-env and fish-agents

T2.6. A release publishes the three packages to PyPI at one version and makes a GitHub
release with the same files. Pushing a tag `vX.Y.Z` does it; `.github/workflows/release.yml`
builds, checks and publishes, and nobody uploads anything by hand (D52).

**Time needed:** the one-time setup about 15 minutes; a release about 15 minutes, most of it
CI.

## One-time setup

PyPI and GitHub must both trust the release workflow before the first release. No password
or token is stored anywhere: PyPI accepts uploads of each package from this repository's
`release.yml`, running in that package's environment, and from nothing else.

1. **PyPI account.** Sign in at <https://pypi.org> (create an account if needed) and turn on
   two-factor authentication; PyPI requires it to publish.
2. **Pending trusted publishers.** At <https://pypi.org/manage/account/publishing/>, under
   *Add a new pending publisher*, choose *GitHub* and add one publisher for each of
   the three packages. Owner `thetruthisntsweet`, repository name `fish` and workflow name
   `release.yml` are the same for all three; the project name and environment name differ:

   | PyPI Project Name | Environment name |
   |---|---|
   | `fish-rules` | `pypi-rules` |
   | `fish-env` | `pypi-env` |
   | `fish-agents` | `pypi-agents` |

   Each needs its own environment because PyPI accepts only one pending publisher per
   repository, workflow and environment ("A pending trusted publisher matching this
   configuration has already been registered for a different project name").

   A pending publisher does not reserve the name: until the first upload creates the project,
   anyone can still register it. Do this shortly before the first release. After the first
   release each one becomes the project's ordinary trusted publisher (the project's
   *Publishing* settings).
3. **The three environments.** On GitHub, *Settings > Environments > New environment*, once
   each for `pypi-rules`, `pypi-env` and `pypi-agents`. In each, under *Deployment branches
   and tags*, choose *Selected branches and tags* and add a **tag** rule `v*`, so only a
   version tag can publish. In `pypi-rules` only, under *Required reviewers*, add yourself:
   the release then waits for your approval once the files have been built and checked.
   fish-env and fish-agents publish only after fish-rules, in the same run, so that one
   approval covers all three.
4. **Protect the tags.** *Settings > Rules > Rulesets > New ruleset > New tag ruleset*, name
   `releases`, enforcement *Active*, target `v*`, rules *Restrict updates* and *Restrict
   deletions*. A version on PyPI can never be replaced, so its tag must not move either.

## Making a release

1. **Prepare it in a pull request.**
   - Set the version in `packages/fish-rules/pyproject.toml`, `packages/fish-env/pyproject.toml`
     and `packages/fish-agents/pyproject.toml`. For a new minor version (0.1 to 0.2), also
     move the sibling bounds (`fish-rules>=0.2,<0.3`). Then `uv lock`.
   - Rename the `## Unreleased` heading at the top of `CHANGELOG.md`, where changes are listed
     as they merge, to `## X.Y.Z (YYYY-MM-DD)`, dated the day you will tag, and set `version`
     and `date-released` in `CITATION.cff` to match. The entry becomes the GitHub release's
     text.
   - `scripts/check.sh`, then the pull request as usual. `test_packaging.py` fails if the
     versions, changelog and citation disagree.
2. **Rehearse.** After merging, *Actions > Release > Run workflow* on `main`. It builds and
   checks everything a release would and publishes nothing. It should pass.
3. **Tag.**

```bash
   git checkout main && git pull
   uv run --no-project --python 3.14 python scripts/check_release.py vX.Y.Z
   git tag -a vX.Y.Z -m "fish X.Y.Z"
   git push origin vX.Y.Z
```

4. **Approve.** The *Release* run builds and checks, then waits at *Publish fish-rules to
   PyPI*: open the run and *Review deployments > Approve*. It uploads fish-rules, fish-env and
   fish-agents in that order, then makes the GitHub release.
5. **Check it as a user would**, from outside the repository (PyPI may take a minute):

```bash
   cd /tmp && uv run --no-project --python 3.14 --with "fish-agents[env]==X.Y.Z" \
     python -c "import fish_agents, fish_env, fish_rules; print(fish_agents.__version__)"
```

   It prints `X.Y.Z`.

## When something fails

| What failed | What to do |
|---|---|
| *Build and check the release* | Nothing was published. Fix it on `main` through a pull request, then move the tag: `git push --delete origin vX.Y.Z && git tag -d vX.Y.Z`, and tag again. (The `releases` ruleset blocks this: set it to *Disabled* meanwhile.) |
| A *Publish … to PyPI* job, with an error from PyPI about trust | That package's trusted publisher fields (setup step 2) or its environment's name differ from the workflow's. Correct them, then *Re-run failed jobs*. |
| A *Publish … to PyPI* job, partway | *Re-run failed jobs*: files already on PyPI are skipped. Never move the tag once anything is on PyPI. |
| *GitHub release* | *Re-run failed jobs*. |
| A published release is broken | PyPI never lets a version's files be replaced or reused. Yank it (the project on PyPI, *Manage > Releases > Options > Yank*), giving the reason, so installers skip it unless pinned; then fix it and release the next patch version, saying in the changelog why. |
