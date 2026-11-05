//! Registered jobs use monotonic elapsed seconds; no job registers itself.
//! A delayed poll skips missed starts, and a running job never overlaps itself.
use std::io;
use std::num::NonZeroU64;
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicBool, Ordering},
};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

/// Process-local run generation; two runs can have the same wall-clock time.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct TickRun {
    pub generation: thread::ThreadId,
    pub started_at: u64,
}
#[derive(Clone, Default)]
pub struct TickMonitor(Arc<Mutex<Option<TickRun>>>);
pub(crate) struct TickRunGuard(TickMonitor, TickRun);
impl TickMonitor {
    pub fn current(&self) -> Result<Option<TickRun>, String> {
        self.0
            .lock()
            .map(|run| *run)
            .map_err(|_| "tick generation is unavailable".into())
    }
    pub(crate) fn begin(&self, started_at: u64) -> Result<TickRunGuard, String> {
        let run = TickRun {
            generation: thread::current().id(),
            started_at,
        };
        *self
            .0
            .lock()
            .map_err(|_| "tick generation is unavailable")? = Some(run);
        Ok(TickRunGuard(self.clone(), run))
    }
}
impl Drop for TickRunGuard {
    fn drop(&mut self) {
        if let Ok(mut current) = self.0.0.lock()
            && *current == Some(self.1)
        {
            *current = None;
        }
    }
}

struct Job {
    name: String,
    every_s: NonZeroU64,
    registered_at: u64,
    next: Option<u64>,
    action: Arc<dyn Fn() + Send + Sync>,
    running: Option<JoinHandle<()>>,
    stop: Option<Arc<AtomicBool>>,
    monitor: Option<TickMonitor>,
}

#[derive(Default)]
pub struct Scheduler {
    jobs: Vec<Job>,
    elapsed_s: u64,
}

impl Scheduler {
    pub fn tick_monitor(&self) -> TickMonitor {
        self.jobs
            .iter()
            .find(|j| j.name == crate::tick::JOB)
            .and_then(|j| j.monitor.clone())
            .unwrap_or_default()
    }
    /// Generation-checked stalled repair; deliberate takeover uses restart_tick.
    pub fn restart_stalled_tick(&mut self, expected: TickRun, deadline: Instant) -> io::Result<()> {
        let current = self
            .jobs
            .iter()
            .find(|job| job.name == crate::tick::JOB)
            .and_then(|job| job.running.as_ref())
            .is_some_and(|run| !run.is_finished() && run.thread().id() == expected.generation);
        if !current || self.tick_monitor().current().map_err(io::Error::other)? != Some(expected) {
            return Err(io::Error::other(
                "observed tick generation changed or completed",
            ));
        }
        self.restart_tick(deadline)
    }
    /// Bounded stop and replacement of this service's tick only.
    pub fn restart_tick(&mut self, deadline: Instant) -> io::Result<()> {
        let job = self
            .jobs
            .iter_mut()
            .find(|j| j.name == crate::tick::JOB)
            .ok_or_else(|| io::Error::other("the service tick is not registered"))?;
        let stop = job
            .stop
            .as_ref()
            .ok_or_else(|| io::Error::other("the service tick has no stop control"))?;
        stop.store(true, Ordering::SeqCst);
        while job.running.as_ref().is_some_and(|run| !run.is_finished()) {
            let left = deadline.saturating_duration_since(Instant::now());
            if left.is_zero() {
                return Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "tick stop is not confirmed",
                ));
            }
            std::thread::park_timeout(left.min(Duration::from_millis(5)));
        }
        // Keep ownership until confirmed. Dropping an unfinished JoinHandle
        // would detach its writes, not stop them.
        finish(job)?;
        if Instant::now() >= deadline {
            return Err(io::Error::new(
                io::ErrorKind::TimedOut,
                "tick replacement deadline expired",
            ));
        }
        start(job)
    }

    pub(crate) fn register_tick(
        &mut self,
        every_s: NonZeroU64,
        stop: Arc<AtomicBool>,
        monitor: TickMonitor,
        action: impl Fn() + Send + Sync + 'static,
    ) -> Result<(), &'static str> {
        self.register(crate::tick::JOB, every_s, action)?;
        self.jobs.last_mut().unwrap().stop = Some(stop);
        self.jobs.last_mut().unwrap().monitor = Some(monitor);
        Ok(())
    }

    /// First due one period after registration; names must be unique.
    pub fn register(
        &mut self,
        name: &str,
        every_s: NonZeroU64,
        action: impl Fn() + Send + Sync + 'static,
    ) -> Result<(), &'static str> {
        if name.is_empty() || self.jobs.iter().any(|job| job.name == name) {
            return Err("a job needs a nonempty, unique name");
        }
        self.jobs.push(Job {
            name: name.to_owned(),
            every_s,
            registered_at: self.elapsed_s,
            next: self.elapsed_s.checked_add(every_s.get()),
            action: Arc::new(action),
            running: None,
            stop: None,
            monitor: None,
        });
        Ok(())
    }

    /// Called with seconds elapsed on the service's monotonic clock.
    /// Returns exactly the jobs started, in registration order.
    pub fn poll(&mut self, elapsed_s: u64) -> io::Result<Vec<String>> {
        if elapsed_s < self.elapsed_s {
            return Err(io::Error::other("the scheduler clock went backwards"));
        }
        self.elapsed_s = elapsed_s;
        let mut started = Vec::new();
        for job in &mut self.jobs {
            if job.running.as_ref().is_some_and(JoinHandle::is_finished) {
                finish(job)?;
            }
            if job.next.is_some_and(|due| due <= elapsed_s) {
                // Keep the original cadence, even if this start is skipped.
                job.next = ((elapsed_s - job.registered_at) / job.every_s)
                    .checked_add(1)
                    .and_then(|n| n.checked_mul(job.every_s.get()))
                    .and_then(|n| job.registered_at.checked_add(n));
                if job.running.is_none() {
                    start(job)?;
                    started.push(job.name.clone());
                }
            }
        }
        Ok(started)
    }

    /// Wait for the current run of one job, e.g. during a controlled shutdown.
    pub fn wait(&mut self, name: &str) -> io::Result<()> {
        let job = self
            .jobs
            .iter_mut()
            .find(|job| job.name == name)
            .ok_or_else(|| io::Error::other("no registered job has that name"))?;
        finish(job)
    }
}

fn finish(job: &mut Job) -> io::Result<()> {
    if let Some(run) = job.running.take() {
        run.join()
            .map_err(|_| io::Error::other(format!("scheduled job {:?} panicked", job.name)))?;
    }
    Ok(())
}

fn start(job: &mut Job) -> io::Result<()> {
    if let Some(stop) = &job.stop {
        stop.store(false, Ordering::SeqCst);
    }
    let action = Arc::clone(&job.action);
    job.running = Some(thread::Builder::new().spawn(move || action())?);
    Ok(())
}
