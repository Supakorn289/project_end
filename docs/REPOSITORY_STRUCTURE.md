# Repository Structure Policy

The current application has a mature runtime and Manager tool registry that reference several root-level calibration/test scripts by filename.

For the public v1 release:

- keep runtime-critical scripts in their current paths
- remove generated/private artifacts
- remove clearly obsolete/broken files
- document script categories instead of aggressively moving files

A larger `src/`, `tools/`, `hardware_tests/` reorganization should be done only in a later major release with integration tests because moving scripts can break Manager tool paths and systemd/deployment assumptions.
