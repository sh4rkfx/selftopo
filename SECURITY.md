# Security policy

selftopo handles health data and credentials: GitHub tokens in the browser, Garmin, Hevy and
YAZIO credentials in workflow secrets and caches. Please report anything that could expose them.

## Reporting

Use GitHub's private reporting: **Security → Report a vulnerability** in this repository. Please
do not open a public issue. Include what is affected, how to reproduce it and what an attacker
could gain. Do not include anyone's health data or real credentials.

You will get an answer within a week. Fixes are released as a patch version and the `v2` tag is
moved, so data repositories pick them up with their next run.

## Supported versions

| Version | Supported |
|---|---|
| 2.x (tag `v2`) | yes |
| 1.x (tag `v1`) | no; update to 2.x, your data stays compatible |
| older states of `main` before 1.0.0 | no |

## Scope

In scope: this repository's code, the dashboard, the workflow in `templates/data-repo/` and the
template repository. Out of scope: Garmin Connect, Hevy and YAZIO themselves, GitHub, and the
security of a user's own data repository settings (for example collaborators with write access).
