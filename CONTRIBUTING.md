# Contributing

Run tool tests and inspect the source diff before staging explicit file paths. Do not
use a blanket add command in a workspace containing local instructions or logs.

Install the local guards with `python3 tools/apex.py hooks` before the first commit.
They check staged content, commit messages and outgoing history. They preserve existing
hooks rather than overwrite another policy. Hooks are local safety checks, not server-side
access control; do not bypass them.

The tool suite runs Git itself against temporary repositories to check rejected
commits, recovery after unstaging local files and outgoing history. Its push tests
use a temporary bare repository on disk, with no network destination. Fixture authors
and Git configuration are isolated from the contributor's settings.

Use one short commit subject, at most 72 characters:

```text
fix(audio): initialize ALC294 speaker amplifier
```

Allowed types: feat, fix, docs, style, refactor, perf, test, build, ci, chore and revert.
Scope is optional. Do not include a body, footer or co-author. Use the contributor's
existing Git identity. Put details and evidence in an issue or PR when one is created.

Product documentation belongs in Git. Agent instructions, handover notes, hardware logs,
credentials and biometric data stay outside the repository. A local AGENTS.md pointer
may remain visible as untracked; do not add an ignore rule for it. If private material
is staged, remove it from the index before committing. Deleting it in a later commit
does not remove it from history.

Current build sources are UTF-8 text. The guards reject opaque binary blobs even under
an innocuous filename, so renamed sensor data cannot pass as an ordinary binary asset.
Fonts and other upstream binaries use checksum-pinned downloads. A new binary source
format needs a reviewed packaging route. Textual secrets still require diff review;
no filename or content scanner can identify every private note.

Changes to kernel, driver, firmware, PAM, GNOME or initramfs invalidate related results.
Never turn missing hardware evidence into a PASS because a VM or unit suite succeeded.
