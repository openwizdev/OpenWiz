//! Bounded observations only. Unknown tool reads never establish absence.
use super::*;
use openwiz_adapter_github::fleets::GitHubFleets;
use openwiz_core::{
    fleet::{fleets::FleetsSource, model::IssueState},
    source::SourceError,
};
use std::{
    collections::BTreeSet,
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    time::Duration,
};
fn unread(reason: &str) -> Unread {
    Unread {
        gap: Gap::CommandFailed,
        reason: NonEmpty::new(reason).unwrap(),
    }
}
fn failure(e: &SourceError) -> Unread {
    Unread {
        gap: match e {
            SourceError::TimedOut { .. } => Gap::TimedOut,
            SourceError::Malformed { .. } => Gap::Malformed,
            SourceError::NotFound { .. } => Gap::NotFound,
            _ => Gap::CommandFailed,
        },
        reason: NonEmpty::new("CloudRoom health observation could not be read").unwrap(),
    }
}
pub(super) fn read(health: &Health, port: u16) -> Result<Seen, String> {
    let deadline = Instant::now() + openwiz_core::limits::RUN_BUDGET;
    let running = openwiz_adapter_cloudroom::locate::program(health.room.program()).is_ok();
    let loops = if running {
        match health.room.health_loops(deadline) {
            Ok(rows) => Listed::Read(rows),
            Err(e) => Listed::Unread(failure(&e)),
        }
    } else {
        Listed::Unread(Unread {
            gap: Gap::CloudroomNotRunning,
            reason: NonEmpty::new("CloudRoom is not running, so its loops can't be read").unwrap(),
        })
    };
    let fleet_threads = match fleets(health, running, deadline) {
        Ok(rows) => Listed::Read(rows),
        Err(why) => Listed::Unread(unread(why)),
    };
    let server = probe(
        port,
        Duration::from_secs(health.config["server"]["probe_timeout_s"].as_u64().unwrap()),
    );
    let value = health.snapshot()?;
    let tick_running_since = if value["tick"]["running"].is_null() {
        None
    } else {
        Some(Timestamp(
            i64::try_from(
                value["tick"]["running"]["started_at"]
                    .as_u64()
                    .ok_or("tick start is unread")?,
            )
            .map_err(|_| "tick start is out of range")?,
        ))
    };
    Ok(Seen {
        cloudroom: if running {
            CloudRoomSeen::Running
        } else {
            CloudRoomSeen::NotRunning
        },
        loops,
        tick_running_since,
        fleet_threads,
        server,
    })
}
fn fleets(
    health: &Health,
    running: bool,
    deadline: Instant,
) -> Result<Vec<SeenFleetThread>, &'static str> {
    let gh = TickReads::with_executor(health.github.clone());
    if !gh
        .repository(deadline)?
        .name
        .eq_ignore_ascii_case(&health.repository().to_string())
    {
        return Err("health repository does not match the config");
    }
    let list = GitHubFleets::with_executor(health.github.clone())
        .issues(deadline)
        .map_err(|_| "open specs could not be read")?;
    if list.cut_short {
        return Err("open spec list may be truncated");
    }
    let mut out = Vec::new();
    let mut specs = BTreeSet::new();
    for issue in list.rows {
        if issue.state != IssueState::Open || issue.sub_issues.total == 0 {
            continue;
        }
        if !specs.insert(issue.number) {
            return Err("open spec list names a spec twice");
        }
        let comments = gh.comments(issue.number, deadline)?;
        let Some((thread, record)) = ownership(health, issue.number, &comments, deadline)? else {
            continue;
        };
        let record = Some(record);
        let active = record
            .as_ref()
            .and_then(|record| {
                openwiz_adapter_cloudroom::loops::recorded_fleet_loop(record, &thread)
                    .ok()
                    .map(|loop_id| takeover::Binding {
                        spec: issue.number,
                        thread: thread.clone(),
                        loop_id,
                        record: record.clone(),
                    })
            })
            .is_some_and(|binding| {
                health
                    .snapshot()
                    .is_ok_and(|v| takeover::active(&v, &binding))
            });
        let seen = if !running {
            ThreadSeen::Unknown(Unread {
                gap: Gap::CloudroomNotRunning,
                reason: NonEmpty::new("CloudRoom is not running, so the thread can't be read")
                    .unwrap(),
            })
        } else if active {
            ThreadSeen::Present
        } else {
            match health.room.health_thread_owned(
                &thread,
                &Id::parse(health.config["project"].as_str().unwrap()).unwrap(),
                deadline,
            ) {
                Ok(true) => ThreadSeen::Archived,
                Ok(false) => ThreadSeen::Present,
                Err(SourceError::NotFound { .. }) => ThreadSeen::NotFound,
                Err(e) => ThreadSeen::Unknown(failure(&e)),
            }
        };
        out.push(SeenFleetThread {
            spec: issue.number,
            thread,
            seen,
        });
    }
    Ok(out)
}
fn probe(port: u16, timeout: Duration) -> Known<ServerBroken> {
    let result = (|| -> Result<(), ServerBroken> {
        let until = Instant::now()
            .checked_add(timeout)
            .ok_or(ServerBroken::TimedOut)?;
        let addr = SocketAddr::from(([127, 0, 0, 1], port));
        let mut socket = TcpStream::connect_timeout(&addr, timeout).map_err(|e| {
            if matches!(
                e.kind(),
                std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock
            ) {
                ServerBroken::TimedOut
            } else {
                ServerBroken::Refused
            }
        })?;
        socket
            .set_write_timeout(Some(until.saturating_duration_since(Instant::now())))
            .map_err(|_| ServerBroken::WrongAnswer)?;
        write!(
            socket,
            "GET /api/v1/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
        )
        .map_err(|_| ServerBroken::TimedOut)?;
        let cap = openwiz_server::Limits::default().max_head_bytes;
        let mut bytes = Vec::new();
        let mut chunk = [0u8; 1024];
        loop {
            let left = until.saturating_duration_since(Instant::now());
            if left.is_zero() {
                return Err(ServerBroken::TimedOut);
            }
            socket
                .set_read_timeout(Some(left))
                .map_err(|_| ServerBroken::TimedOut)?;
            let n = socket.read(&mut chunk).map_err(|e| {
                if matches!(
                    e.kind(),
                    std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock
                ) {
                    ServerBroken::TimedOut
                } else {
                    ServerBroken::WrongAnswer
                }
            })?;
            if n == 0 {
                return Err(ServerBroken::WrongAnswer);
            }
            bytes.extend_from_slice(&chunk[..n]);
            if bytes.len() > 2 * cap {
                return Err(ServerBroken::WrongAnswer);
            }
            let Some(at) = bytes.windows(4).position(|w| w == b"\r\n\r\n") else {
                if bytes.len() > cap {
                    return Err(ServerBroken::WrongAnswer);
                }
                continue;
            };
            let head = std::str::from_utf8(&bytes[..at]).map_err(|_| ServerBroken::WrongAnswer)?;
            let mut lines = head.split("\r\n");
            let status = lines.next().unwrap_or_default();
            if !(status.starts_with("HTTP/1.1 200 ") || status.starts_with("HTTP/1.0 200 ")) {
                return Err(ServerBroken::WrongAnswer);
            }
            let lengths = lines
                .filter_map(|l| l.split_once(':'))
                .filter(|(key, _)| key.eq_ignore_ascii_case("content-length"))
                .map(|(_, v)| v.trim().parse::<usize>())
                .collect::<Vec<_>>();
            let [Ok(len)] = lengths.as_slice() else {
                return Err(ServerBroken::WrongAnswer);
            };
            if *len > cap {
                return Err(ServerBroken::WrongAnswer);
            }
            let body = &bytes[at + 4..];
            if body.len() < *len {
                continue;
            }
            if body.len() != *len {
                return Err(ServerBroken::WrongAnswer);
            }
            let doc = openwiz_adapter_github::tick::document(body)
                .map_err(|_| ServerBroken::WrongAnswer)?;
            return if doc["server"]["name"] == "openwiz-server" {
                Ok(())
            } else {
                Err(ServerBroken::WrongAnswer)
            };
        }
    })();
    match result {
        Ok(()) => Known::Healthy,
        Err(broken) => Known::Broken(broken),
    }
}

/// Resolve public ownership privately, then give the exact-loop adapter its
/// existing thread-bound representation. That representation is never posted.
pub(super) fn ownership(
    health: &Health,
    spec: Number,
    comments: &[openwiz_adapter_github::tick::Comment],
    deadline: Instant,
) -> Result<Option<(Id, String)>, &'static str> {
    let Some(line) = comments
        .iter()
        .filter_map(|c| c.body.lines().next())
        .rfind(|s| {
            s.starts_with("launch-fleet: fleet thread ")
                || s.starts_with("launch-fleet: fleet active")
        })
    else {
        return Ok(None);
    };
    if let Some(loop_id) = line.strip_prefix("launch-fleet: fleet active, loop ") {
        let loop_id = Id::parse(loop_id).ok_or("fleet active record has an unread loop id")?;
        let path = health.root.join("service/fleet-map.json");
        records::checked(&path, false).map_err(|_| "private fleet map is unread or unsafe")?;
        let bytes = std::fs::read(path).map_err(|_| "private fleet map is unread")?;
        let map = openwiz_adapter_github::tick::document(&bytes)
            .map_err(|_| "private fleet map is malformed")?;
        openwiz_adapter_github::tick::object(&map, &["repo", "threads"])
            .map_err(|_| "private fleet map is malformed")?;
        if map["repo"].as_str() != Some(health.repository().to_string().as_str()) {
            return Err("private fleet map belongs to another repository");
        }
        let rows = map["threads"]
            .as_object()
            .ok_or("private fleet map is malformed")?;
        if rows
            .values()
            .any(|v| v.as_str().and_then(Id::parse).is_none())
        {
            return Err("private fleet map has an invalid identity");
        }
        let thread = rows
            .get(&format!("fleet:{spec}"))
            .and_then(Value::as_str)
            .and_then(Id::parse)
            .ok_or("private fleet owner is unresolved")?;
        let bound = format!(
            "launch-fleet: fleet thread {}, loop {}",
            thread.as_str(),
            loop_id.as_str()
        );
        return Ok(Some((thread, bound)));
    }
    // Legacy thread-bearing records are readable only on a positively private
    // repository. Unknown visibility has the public rules, never a name bypass.
    let call = openwiz_adapter_github::allowlist::Invocation::new(&[
        "repo",
        "view",
        "--json",
        "nameWithOwner,isPrivate",
    ])
    .ok_or("repository privacy read is unavailable")?;
    let metadata = health
        .github
        .run(&call, deadline)
        .ok()
        .and_then(|v| openwiz_adapter_github::tick::document(&v).ok());
    if !metadata.as_ref().is_some_and(|v| {
        openwiz_adapter_github::tick::object(v, &["nameWithOwner", "isPrivate"]).is_ok()
            && v["nameWithOwner"]
                .as_str()
                .is_some_and(|s| s.eq_ignore_ascii_case(&health.repository().to_string()))
            && v["isPrivate"] == true
    }) {
        return Err("legacy fleet ownership is not verified private");
    }
    let tail = line
        .strip_prefix("launch-fleet: fleet thread ")
        .ok_or("malformed fleet ownership record")?;
    let thread = if let Some((thread, loop_id)) = tail.split_once(", loop ") {
        Id::parse(loop_id).ok_or("fleet ownership record has an unread loop id")?;
        thread
    } else {
        tail
    };
    let thread = Id::parse(thread).ok_or("fleet ownership has an unread thread id")?;
    Ok(Some((thread, line.to_owned())))
}
