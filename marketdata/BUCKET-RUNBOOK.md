# Market-data bucket runbook (CLOSE-1 WP7)

Status: documentation only. Nothing here has been run against a real bucket. No
bucket, project, key or credential was created, read or tested in writing it.

Owner: Bill. Only Bill creates the bucket and its keys (hard limit in every order).

## What goes to the bucket

Only verified packs under `<store>/20_curated/packs/`. `marketdata/sync.py`
refuses any source outside that root, never uploads `00_raw`, and verifies each
object's SHA-256 after upload. Files containing a security identifier never reach
`20_curated` (DATA-1 v0.2 and SIM-1D), so they cannot reach the bucket.

## Before the first upload: two checks in the Railway dashboard

1. **Versioning or object lock.** If Railway Storage Buckets offer either, turn it
   on. If not, the offline SSD copy (`sync --to ssd`) is mandatory, because a
   leaked read-write key could otherwise delete curated packs.
2. **A read-only key for SIM.** If Railway can issue a read-only credential, give
   only that one to any deployed simulator. If not, the read-write key stays on the
   Mac and is never set on a deployed service.

Create the bucket in a Railway project separate from Aureon production.

## Environment the code reads

| Variable | Read by | Meaning |
|---|---|---|
| `CFMA_S3_ENDPOINT` | `marketdata/sync.py` | The bucket's S3 endpoint URL from the Railway dashboard. `--endpoint-url` overrides it. |
| `AWS_ACCESS_KEY_ID` | boto3 default credential chain | Access key Railway shows for the bucket. |
| `AWS_SECRET_ACCESS_KEY` | boto3 default credential chain | Secret key Railway shows for the bucket. |
| `AWS_DEFAULT_REGION` | boto3 | The region value Railway shows (often `auto`). |

Set them in the shell for the one command, from macOS Keychain, never in a file
in any repository. The repository guard (`python -m marketdata guard`) blocks
secret files.

## First sync

From the Atreides checkout, with the store at its default root:

```bash
python -m marketdata verify ~/Data/cfma-data/20_curated/packs/repo-spike-2019/5
python -m marketdata sync --to bucket \
  ~/Data/cfma-data/20_curated/packs/repo-spike-2019/5 \
  s3://<bucket-name>/packs/repo-spike-2019/5
```

Run the same `sync` again. The second run must upload zero objects; that is the
idempotence check.

## Verifying what landed

The sync command compares each object's stored `sha256` metadata with the local
digest after upload and stops on any mismatch. To check independently, list the
prefix and compare each object's `sha256` metadata with `marketdata/pack-locks.json`.

## Known risk, untested

Railway documents virtual-hosted-style bucket URLs. `sync.py` creates the boto3
client without an explicit addressing style. If the first upload fails with an
addressing or "bucket not found" error, the fix is one line in `sync.py`
(`Config(s3={"addressing_style": "virtual"})`), made in a pull request, not by hand
on the Mac.

## Never

- `--prune` on the first sync.
- A key in a commit, a report, `.env` in a repository, or a deployed service's
  variables unless it is the read-only key.
