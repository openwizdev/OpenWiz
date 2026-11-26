# Download counts

OpenWiz is installed from GitHub release assets in this repository. The public
site and the install guide send people to that same install. No package
registry publishes the program. This tool reads the download totals GitHub
already keeps for those assets.

```sh
python3 -I tools/downloads/counts.py
python3 -I tools/downloads/counts.py --json
```

`package_downloads` is the sum of `openwiz-<version>-<target>.tar.gz` downloads.
One install of one target downloads one of those archives. `asset_downloads`
also counts the checksum and manifest files fetched beside the archive, and any
release check that downloaded them. Draft releases are left out. Prereleases
are included and marked.

The same report can be printed from Actions by running the **Download counts**
workflow.

GitHub's `download_count` is a running total of asset downloads. It includes
repeated downloads. It does not include git clones, GitHub's generated source
zip and tar links, site visits, or installs from a package registry. The read
sends no client event and records no user, device, or network identifier. A
`GITHUB_TOKEN` or `GH_TOKEN` in the environment is sent only as a request
header to raise the API rate limit, and it is never printed.
