//! Health jobs request bounded work from the existing runtime owner.
use super::RuntimeFixes;
use crate::scheduler::{Scheduler, TickMonitor, TickRun};
use std::{
    sync::{
        Arc,
        mpsc::{self, Receiver, SyncSender},
    },
    time::Instant,
};
enum Kind {
    Tick,
    StalledTick(TickRun),
    Server,
}
pub struct Request {
    kind: Kind,
    until: Instant,
    reply: SyncSender<Result<(), String>>,
}
struct Control(SyncSender<Request>, TickMonitor);
pub fn channel() -> (Arc<dyn RuntimeFixes>, Receiver<Request>) {
    channel_with_monitor(TickMonitor::default())
}
pub fn channel_with_monitor(monitor: TickMonitor) -> (Arc<dyn RuntimeFixes>, Receiver<Request>) {
    let (tx, rx) = mpsc::sync_channel(1);
    (Arc::new(Control(tx, monitor)), rx)
}
impl Control {
    fn request(&self, kind: Kind, until: Instant) -> Result<(), String> {
        let (tx, rx) = mpsc::sync_channel(1);
        self.0
            .try_send(Request {
                kind,
                until,
                reply: tx,
            })
            .map_err(|_| "runtime repair owner is unavailable")?;
        rx.recv_timeout(until.saturating_duration_since(Instant::now()))
            .map_err(|_| "runtime repair completion is unconfirmed")?
    }
}
impl RuntimeFixes for Control {
    fn current_tick(&self) -> Result<Option<TickRun>, String> {
        self.1.current()
    }
    fn restart_stalled_tick(&self, expected: TickRun, deadline: Instant) -> Result<(), String> {
        self.request(Kind::StalledTick(expected), deadline)
    }
    fn restart_tick(&self, deadline: Instant) -> Result<(), String> {
        self.request(Kind::Tick, deadline)
    }
    fn restart_server(&self, deadline: Instant) -> Result<(), String> {
        self.request(Kind::Server, deadline)
    }
}
impl Request {
    /// True only when the server was replaced. Its owner updates status then,
    /// even if the requesting job stopped before it could receive the reply.
    pub fn apply(
        self,
        jobs: &mut Scheduler,
        server: &mut openwiz_server::Server,
        replace: impl FnOnce() -> Result<openwiz_server::Server, String>,
    ) -> bool {
        let mut replaced = false;
        let outcome = (|| {
            if Instant::now() >= self.until {
                return Err("runtime repair request expired before dispatch".to_owned());
            }
            match self.kind {
                Kind::Tick => jobs
                    .restart_tick(self.until)
                    .map_err(|_| "tick stop/replacement was not confirmed".to_owned()),
                Kind::StalledTick(expected) => jobs
                    .restart_stalled_tick(expected, self.until)
                    .map_err(|_| {
                        "observed tick changed, completed, or stop was unconfirmed".to_owned()
                    }),
                Kind::Server => {
                    server
                        .shutdown(self.until)
                        .map_err(|_| "server stop was not confirmed".to_owned())?;
                    if Instant::now() >= self.until {
                        return Err("server replacement deadline expired".to_owned());
                    }
                    let next = replace()?;
                    *server = next;
                    replaced = true;
                    Ok(())
                }
            }
        })();
        let _ = self.reply.send(outcome);
        replaced
    }
}
