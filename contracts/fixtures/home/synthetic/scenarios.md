# Synthetic home cases

These examples specify the expected result for each rule. The record and
watchdog cases also have executable fixtures in this directory.

## Machine

An always-on Linux box and an always-on Mac can each run `t3 up` as a
service with T3 Connect signed in. A Boat box can do the same when the
owner turns Boat on. An unsigned-in service fails the home check.

## Project

A synthetic owner's checkout points to a private records remote. A
synthetic user's checkout points to their own OpenWiz remote. In each
case the one T3 project tracks issues from that checkout's remote.

## The Wiz thread

The thread pinned in that project has the exact title `Wiz`. After the
orchestrator setting changes, the current session keeps its selection
and a new session reads the updated selection.

## Boot inputs

A new session starts with an empty chat history. It reads the home
handoff and home state before any other input.

## State

The manifest in [valid.json](valid.json) keys each installed task by its
loop id. `.openwiz/home/synthetic-sweep/state.json` holds sweep state and
`.openwiz/home/synthetic-sweep/ok.log` receives its line as the run's
last step.

## Watchdog

In [watchdog.json](watchdog.json), a dispatched interval task with a
stale acknowledgment is late. A fixed-time task with no acknowledgment
is only late after its grace period. A failed task is late even when
there is a fresh acknowledgment.

## Installed loops

With one running fleet and no optional loops, the home installs
`home-watchdog`, `settings-backup`, `update-check`, and that fleet's
`fleet-check`. Enabling a synthetic sweep adds that loop from its file.

## Chat

The owner asks about a fleet in Wiz and Wiz answers. The builder records
its result on GitHub and wakes through the driver. A loop that needs a
decision files a Needs-you card.

## Updates

A verified synthetic release is offered. Until a yes is recorded the
installed version stays in place. After a recorded owner yes, the
update keeps the existing drivers and settings.

## Server

The home server is T3's `t3 up`. The local board accepts a connection
to `127.0.0.1`. Binding the board to `0.0.0.0` violates the contract.
