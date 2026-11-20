# Hand-authored Nexus API responses

Used by `tests/test_nexus.py`. The shapes follow the Nexus v1 REST and v2 GraphQL responses the toolkit reads
(`/games/<domain>/mods/<id>.json`, `files.json`, `files/<file_id>.json` (`fileinfo.json`), `files/<file_id>/download_link.json`
(`download_link.json`: its one mirror is plain `http://`, so the downloader skips it and no test can reach a
network), `changelogs.json`, the GraphQL `mods` search and
`modRequirements`), but every value is made up: no real mod, author or account. Several fields are explicit
`null` on purpose, because Nexus returns them that way and a `.get(key, default)` does not cover a null.
