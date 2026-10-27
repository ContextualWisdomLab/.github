# Offline lease / owned-child / receipt-consumer increment

This central module is runnable locally, not an admitted physical GPU supplier.
The existing reusable workflow and all software/product tests remain unchanged.
Native activation has no command or adapter. Do not pin a product caller on the
strength of these diagnostics.

## Run

From this repository, with an existing private non-symlink directory:

```sh
python3 -m scripts.ci.fast_mlsirm_local_supervisor local --root /absolute/private/attempt --mode success
python3 -m pytest tests/test_fast_mlsirm_local_supervisor.py tests/test_fast_mlsirm_receipts.py
```

CLI exit0 means only a fixed local child exited0, its original Popen wait matched,
and local settlement persistence completed before lock close. Child failure,
timeout and handled refusal exit1; unsupported/native command exit2. No environment
variable or JSON Boolean can enable hardware. `hardware_admitted` is always false.

## Finite ownership contract

Only source-defined descendant-free Python snippets execute under `-I -S`, empty
environment, closed inherited descriptors and DEVNULL stdio. The diagnostic stall
self-terminates after one second. This is not arbitrary command containment.
A real nonblocking kernel flock on `local.lock` precedes an exclusive durable
`attempt.json` claim, child launch, wait, receipt check and atomic fsynced settlement.
The same lock inode is never unlinked or replaced. Attempts are single-use, even
following success; the durable claim prevents silent re-admission after process
death (flock itself is released by the kernel on process exit). No automatic stale
claim cleanup or PID-based recovery is implemented.

Cancellation Event, timeout, and post-spawn BaseException drain the original
returned child. Signal and wait attempts are independent. If wait or settlement
persistence is uncertain, the surviving Python owner retains the actual handle
and lock in `_UNRESOLVED`; another launch through that owner is forbidden.
`reconcile()` retries exact wait/journal only in that same surviving owner.
A close error is not retried with a potentially reused descriptor. Persistent
native wait failure, interruption inside Popen before handle return, interpreter
SIGKILL and arbitrary descendant escape are **not proven settlement guarantees**.
The fixed finite child restriction is essential; no shared resource is acquired.

The private root and ancestors must remain caller-owned and quiescent. Symlinks,
parent traversal, nonregular bounded inputs, writable declared immutable input,
hard-linked inputs/locks and digest drift reject. These checks do not create an
atomic sandbox against a malicious same-UID writer or prove privileged source
custody. Input bytes are snapshotted and the parsed binding is copied before use;
no later pathname reload controls the child.

## Connected local receipt path

The library `Supervisor.run("receipt", input_path=..., input_sha256=...,
expected=...)` reads a read-only, SHA256-bound input object containing exactly
`scope: synthetic-local-only` and `binding`. Expected identities are supplied
separately by the trusted caller; `lease` must equal this owner's generated token.
The actual owned fixed child emits **synthetic** local JUnit/call envelope bytes.
It does not execute the named numerical tests. After exact child wait, the real
receipt consumer joins those bytes before settlement; malformed evidence returns
`receipt_rejected`, not `local_success`.

The closed `local-exact3-v1` envelope checks nonempty exact-once three required
node IDs, unique call IDs, passed outcomes, matching JUnit classname/name and
properties, exact source SHA, extension digest, supplier SHA, run ID, attempt,
job and lease, plus JUnit byte digest. Missing/duplicate/extra/skipped/failed,
wrong-source/run/call evidence rejects. UTF8/bounds/duplicate-key/DTD restrictions
are explicit. The format is a **new synthetic protocol for testing the consumer**,
not a claimed existing product receipt API or authenticated native provenance.

Reuses central `review_admission_controller._open_regular_nofollow` and
`_atomic_write`; its queue state/update transaction is not a child-lifetime lease
and is intentionally not repurposed. Existing operator Docker/Actions source was
read as data only and is not copied, invoked or relabelled as GPU isolation.

## Native boundary still missing

An admitted existing-owner physical GPU isolation/lease adapter, durable exclusive
GPU claim, compiled-extension/check-out custody and authenticated same-call native
adapter/dispatch provenance reaching the numerical consumer are absent. Current
product fit results do not export those identities. The unchanged three numerical
tests (q121 with its existing STAGE5_HIGH_Q=1) still need genuine execution and
nonempty authentic receipts before a workflow hardware gate can replace its hold.
No runner registration/restart, SSH, actual GPU lease, dispatch, publication or
merge is part of this change. Parent owns independent whole-source review.
