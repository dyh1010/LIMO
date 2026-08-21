# Arm persistent safety latch contract

This is a local, offline filesystem contract. It never connects to the arm,
gripper, ROS graph, or a vendor runtime. It cannot by itself authorize motion
or prove that a person performed physical isolation.

It is deliberately not called from `ArmGatewayCore`: filesystem latency or a
blocked approval validator must never sit on the core STOP path. A future
release supervisor must own this store through independently bounded I/O,
latch physical-isolation-required before reporting an unresolved STOP, and
bind its runtime release ID and manifest SHA exactly to the approved release.

`PersistentArmSafetyLatch` stores one canonical JSON record with exclusive
initial creation, generation number, previous-record SHA-256, exact release
binding, and active/clear state. Callers cannot select their session identity.
The schema-2 issuance ledger contains a contiguous history of issued
epoch/nonce pairs, a canonical sorted registry of every consumed clearance ID,
and a payload SHA-256. Empty, truncated, malformed, stale-release, noncanonical,
or hash-mismatched ledgers fail closed and are never treated as a new store.

Only a genuinely absent record and ledger may be created. `create` checks both
under the persistent update lock before issuing epoch 1. A repeated `create`
does not call the injected store-ID factory, rewrite the ledger, or advance the
session epoch. An orphan ledger with no record is not recoverable through
`create`; it requires protected, audited operator recovery outside this API.

Every successful `open` appends a new session and advances the canonical record
generation, previous-record chain, and latest-session anchor. The record anchor
must exactly equal the ledger latest session, and every session referenced by
the record must exist in the ledger history. Therefore replacing only the
ledger with a fully re-hashed stale copy cannot restore a superseded clearer.

Every latch request, including a repeated request while already `ACTIVE`,
advances the generation and freezes `minimum_clearing_session_epoch` beyond
the greatest session epoch already issued. Thus a later STOP or physical-
isolation request invalidates any clearance validator already in flight. The
latching session and every session issued before the latch cannot build or
apply a clearance credential. Only the latest ledger-issued process session
may build or commit clearance; a newer session permanently supersedes older
clearers. A credential binds the exact store ID, generation, record hash,
latch epoch/nonce, minimum clearing epoch, clearing epoch/nonce, runtime release
ID, release-manifest SHA, physical-verification artifact and approval artifact.
Forged or stale fields are rejected before the external validator is invoked.
The record also binds a SHA-256 of the complete consumed-clearance registry, so
removing any previously consumed ID from only the ledger fails closed.

`open` requires expected runtime release ID and manifest SHA arguments. It
rejects an internally consistent latch or issuance ledger from another release
before issuing a new session. An active record remains active across a real
process restart.

Updates use a persistent, non-unlinked OS-lock file with an exact marker and
same-directory atomic replacement. Before the first filesystem mutation, the
writer exclusively creates and syncs a canonical `.commit-pending` marker. It
removes that marker only after every data publication, readback, directory sync,
and update-lock exit validation has succeeded. A crash, write failure, readback
failure, post-`replace` directory-sync failure, or update-lock identity failure
leaves the marker present. Every create/open/snapshot/latch/credential/CLEAR
entry point then rejects the store as `COMMIT_UNCERTAIN`; it never exposes a raw
CLEAR record as a successful API state after an exception.

Marker removal is the runtime-visible commit point. If the data and lock checks
succeed but syncing the already-removed marker's directory entry fails, the API
returns the committed result rather than throwing an exception that could be
misread as "not committed". Power-loss durability at and after that point is
still not claimed and remains a target acceptance blocker.

The update-lock pathname is never removed during normal operation, so an old
owner cannot delete a newer owner's lock through a check-then-unlink race.
Record, ledger, pending-marker and lock sidecars must be ordinary files with
exactly one link. Opens use `O_NOFOLLOW` when available, reject Windows reparse
points, compare `lstat` path identity with the opened `fstat` identity, and fail
closed if Windows reparse or stable inode inspection is unavailable. The marker
and path identity are rechecked while the OS lock is held. Failure to acquire,
inspect, or operate the lock fails closed.

After exact external validation, CLEAR commit holds that same update lock and
first atomically adds the clearance ID to the persistent ledger. Only then does
it publish the CLEAR record. If ledger publication fails, CLEAR is not written.
If record publication fails after the ledger update, the ID remains consumed,
and the pending marker blocks all API use pending audited recovery. If record
replacement occurred but its final directory sync failed, raw filesystem bytes
may contain CLEAR, but the pending marker still prevents reopen or snapshot from
reporting CLEAR. The implementation never reuses the ID or guesses the outcome
merely to make the store convenient to recover.

The store path must be an ordinary absolute local filesystem path. Device and
special namespaces are rejected lexically before path resolution or metadata
access. Existing ancestor symbolic links and final-record symbolic links are
rejected. Windows local tests prove the available reparse metadata and
path/inode checks, but Python file replacement cannot prove power-loss
directory-entry durability on Windows. That target property remains `BLOCKED`
until measured on protected storage with an approved recovery design.

Clearance requires an injected external validator returning exact boolean
`True`. SHA-256 chains, epochs and nonces provide local integrity and replay
resistance only; they are not signatures and do not authenticate an operator or
approval authority. A writer able to replace both a valid record and its ledger
can still forge or roll back the pair. Privileged replacement, full-store disk
rollback, and forged local approval artifacts remain possible without protected
storage, signing/TPM-backed identity, and an independent approval service.

Therefore this remains evidence-contract groundwork. The real backend stays
`DISABLED/BLOCKED` until bounded supervisor I/O, protected persistence,
independent approval and release-bound failure behaviour are verified.
