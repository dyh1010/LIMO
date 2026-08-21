# Gripper persistent safety-latch contract

This is a local, pure-filesystem contract. It does not import ROS or a vendor
runtime, connect to a controller, enumerate a device route, energize the tool,
or issue any gripper action. It cannot prove physical isolation or authorize a
real backend.

`PersistentGripperSafetyLatch` uses an append-only directory of immutable
generation records. Initial store creation and every session, latch, and clear
update are serialized by both a process-wide lock and a persistent OS file
lock. The persistent lock covers the complete read, validation, record
construction, and publication transaction. Each generation is written inside
a private pending directory. Before the same-parent publication rename, a
separate transaction marker is durably synchronized in the store. The marker
is removed only after the renamed generation passes parent-directory
synchronization and the writer context has successfully completed its final
lock-file identity check and OS-lock release. Any publication, context-exit, or
unlock failure therefore leaves the marker in place. A restart that sees either
a transaction marker or pending directory refuses to expose a tentative
generation and reports the safety state as BLOCKED. This prevents `clear()`
from raising after publication while a subsequent reopen silently observes
that tentative CLEAR.

Once generation commit synchronization succeeds, failure of the final
marker-deletion cleanup sync does not retroactively report the committed call
as failed. A crash may conservatively restore the marker and block, but cannot
authorize a less-safe state. No prior generation, writer lock, or mutable head
is deleted. Duplicate creation reserves the store directory before invoking
caller-supplied store-ID or session-nonce factories, so a rejected duplicate
cannot consume credentials or trigger factory side effects. A gap, pending
artifact, unknown file, symlink/reparse point, malformed record, broken
SHA-256 chain, stale runtime binding, missing/tampered writer lock, or write
collision fails closed. Record files, transaction markers, and the writer lock
must be ordinary single-link files. Reads bind the pre-open path metadata to
the opened descriptor and re-check the path/inode after the bounded read;
writer-lock acquisition likewise binds the pre-acquisition inode to the opened
and locked descriptor. Same-content inode swaps and hardlink aliases therefore
fail closed in the locally testable contract.

Every store and credential binds the exact runtime release ID, release-manifest
SHA-256, motion-profile ID, distinct motion-profile SHA-256, and unique
increasing approved speed-grade set. `open()` requires those expected values
and rejects a self-consistent but stale store before issuing a new session.

Sessions are issued by the persistent chain with a monotonically increasing
epoch and generated nonce; callers cannot clear by merely self-reporting a
different session string. Every latch request, including ACTIVE-to-ACTIVE
relatch, appends a new generation and freezes the greatest session epoch
already issued. Every session that existed before or created the latest latch
is therefore permanently ineligible to clear it. Only the latest ledger-issued
session may construct or commit a clearance, and that condition is checked
both before and after external validation. A clearing credential must use a
newly issued post-latch epoch/nonce and bind the exact active generation,
record hash, latch boundary, runtime/profile release, physical-verification
artifact, and approval artifact. Clearance IDs are checked against the entire
validated chain before construction, before validation, and again at commit;
replay or any forged field is rejected before it can publish CLEAR.

The validator must return the exact boolean `True`. The module intentionally
does not implement a Python timeout thread around that callback. A relatch or
newly issued session can proceed while validation is outstanding, and its new
generation makes the late result uncommittable. A future independent release
supervisor must still provide a natively bounded approval call.
Local SHA-256 chaining is integrity evidence, not a signature. An actor with
privileged filesystem write access could still replace a whole store, request
a newly issued session, or forge local artifacts. Protected storage,
supervisor-issued process identity, signed approval, monotonic/rollback-proof
state, and independently bounded validation remain required.
The local checks also do not prove a hostile parent/store directory cannot be
renamed during an operation, and they cannot detect privileged rollback or
truncation of an otherwise self-consistent complete store.

Consequently this implementation is contract groundwork only. No production
factory constructs a real gripper backend, and the real gripper remains
`DISABLED/BLOCKED` until transport-level bounded calls/cancellation, an
independent STOP channel, protected persistent latching, exact release binding,
and separately authorized physical evidence all pass review.
