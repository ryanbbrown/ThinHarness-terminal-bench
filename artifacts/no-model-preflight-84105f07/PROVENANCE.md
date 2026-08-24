# Native ThinHarness 84105f07 no-model preflight

This directory is the immutable evidence set for the Harbor/Docker no-model preflight launched as `preflight-20260824-180247-5ed5d5ff`.

- Candidate commit: `84105f07bb9c1ad366fc8fe4fef49e700f5e88ef`
- Durable source default: `https://github.com/ryanbbrown/thinharness.git`
- Authorized run source: a transient bundle built from a clean `/Users/ryanbrown/code/thinharness` checkout whose `HEAD` equaled the candidate commit
- Bundle SHA-256: `fde7f901dd2005e1f0b59e4b53b419bd179b650d858b60464eae77b4b97822fb`
- Wheel build and install: inside the Harbor task container
- Model calls: 0
- Verifier handoff: completed; reward 0.0 is expected because the preflight does not solve the task

The bundle and ThinHarness source are not in this repository. The launch control removed temporary host bundle staging after Harbor exited. The in-container setup removed its bundle and source checkout after it verified the commit and built the wheel. `bash-overflow-full.bin` is the durable Harbor-log copy of the controlled native Bash overflow artifact, not ThinHarness product code.
