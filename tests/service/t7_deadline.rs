//! R1: each public-client caller keeps its own budget during a shared refresh.
use super::*;
use std::sync::mpsc;

struct HeldExchange {
    entered: mpsc::Sender<()>,
    release: Mutex<mpsc::Receiver<()>>,
    calls: AtomicU64,
    first: Result<Vec<u8>, Error>,
    next: Vec<u8>,
}
impl Exchange for HeldExchange {
    fn exchange(&self, _: u64, _: &str, _: &[u8], _: Instant) -> Result<Vec<u8>, Error> {
        if self.calls.fetch_add(1, Ordering::SeqCst) == 0 {
            self.entered.send(()).map_err(|_| Error)?;
            self.release
                .lock()
                .unwrap()
                .recv_timeout(Duration::from_secs(5))
                .map_err(|_| Error)?;
            self.first.clone()
        } else {
            Ok(self.next.clone())
        }
    }
}

struct ObservedClock {
    time: Arc<Time>,
    waiting: mpsc::Sender<()>,
}
impl Clock for ObservedClock {
    fn now_s(&self) -> u64 {
        let now = self.time.now_s();
        if thread::current().name() == Some("t7-r1-waiter") {
            // The old implementation reads this before blocking on the mutex.
            // This proves the waiter entered execute before its deadline.
            self.waiting.send(()).unwrap();
        }
        now
    }
}

struct Held {
    client: Client,
    exchange: Arc<HeldExchange>,
    entered: mpsc::Receiver<()>,
    release: mpsc::Sender<()>,
    waiting: mpsc::Receiver<()>,
}
impl Held {
    fn new(f: &Fixture, first_fails: bool) -> Self {
        let (entered_tx, entered) = mpsc::channel();
        let (release, release_rx) = mpsc::channel();
        let (waiting_tx, waiting) = mpsc::channel();
        let first = f.exchange.response.lock().unwrap().as_bytes().to_vec();
        let mut next: Value = serde_json::from_slice(&first).unwrap();
        next["token"] = json!("synthetic-next-token");
        next["expires_at"] = json!("2030-01-01T02:00:00Z");
        let exchange = Arc::new(HeldExchange {
            entered: entered_tx,
            release: Mutex::new(release_rx),
            calls: AtomicU64::new(0),
            first: if first_fails { Err(Error) } else { Ok(first) },
            next: next.to_string().into_bytes(),
        });
        let client = Client::with_exchange(
            &f.root,
            &f.config(),
            f.root.join("gh"),
            exchange.clone(),
            Arc::new(ObservedClock {
                time: f.clock.clone(),
                waiting: waiting_tx,
            }),
        )
        .unwrap();
        Self {
            client,
            exchange,
            entered,
            release,
            waiting,
        }
    }
}

#[test]
fn shorter_deadline_returns_while_the_shared_exchange_is_still_held() {
    let f = Fixture::new();
    let held = Held::new(&f, false);
    let (finished, refreshing) = thread::scope(|s| {
        let first = s.spawn(|| held.client.execute(&call(), soon()));
        held.entered.recv_timeout(Duration::from_secs(2)).unwrap();
        let (done_tx, done) = mpsc::channel();
        let client = held.client.clone();
        let waiter = thread::Builder::new()
            .name("t7-r1-waiter".into())
            .spawn_scoped(s, move || {
                let result = client.execute(&call(), Instant::now() + Duration::from_millis(100));
                done_tx.send(result).unwrap();
            })
            .unwrap();
        held.waiting.recv_timeout(Duration::from_secs(2)).unwrap();
        // A generous watchdog, not an assertion at a clock edge. The exchange
        // stays explicitly gated until after the waiter's result is captured.
        let finished = done.recv_timeout(Duration::from_secs(1));
        let refreshing = !first.is_finished();
        assert!(f.gh_calls().is_empty());
        held.release.send(()).unwrap();
        first.join().unwrap().unwrap();
        waiter.join().unwrap();
        (finished, refreshing)
    });
    assert!(refreshing, "first refresh must still be held");
    assert_eq!(
        finished.expect("waiter must return before the first exchange is released"),
        Err(Error)
    );
    held.client.execute(&call(), soon()).unwrap();
    assert_eq!(held.exchange.calls.load(Ordering::SeqCst), 1);
    assert_eq!(f.gh_calls().len(), 2, "only the two live-budget calls run");
}

#[test]
fn waking_caller_rechecks_the_clock_before_using_or_refreshing_the_cache() {
    let f = Fixture::new();
    let held = Held::new(&f, false);
    let (first, waiter) = thread::scope(|s| {
        let first = s.spawn(|| held.client.execute(&call(), soon()));
        held.entered.recv_timeout(Duration::from_secs(2)).unwrap();
        let waiter = thread::Builder::new()
            .name("t7-r1-waiter".into())
            .spawn_scoped(s, || held.client.clone().execute(&call(), soon()))
            .unwrap();
        held.waiting.recv_timeout(Duration::from_secs(2)).unwrap();
        f.clock.0.store(NOW + 3601, Ordering::SeqCst);
        held.release.send(()).unwrap();
        (first.join().unwrap(), waiter.join().unwrap())
    });
    assert_eq!(first, Err(Error), "the first response has already expired");
    waiter.expect("the waking caller must mint using the current clock");
    assert_eq!(held.exchange.calls.load(Ordering::SeqCst), 2);
    let calls = f.gh_calls();
    assert_eq!(calls.len(), 1);
    assert_eq!(calls[0]["token"], "synthetic-next-token");
}

#[test]
fn failed_refresh_wakes_another_caller_without_reusing_the_failed_token() {
    let f = Fixture::new();
    let held = Held::new(&f, true);
    // This second caller is allowed its own one mint attempt after the failed
    // caller. Its response is valid at NOW + 3601, not at the stale NOW.
    let (first, finished) = thread::scope(|s| {
        let first = s.spawn(|| held.client.execute(&call(), soon()));
        held.entered.recv_timeout(Duration::from_secs(2)).unwrap();
        let (done_tx, done) = mpsc::channel();
        let client = held.client.clone();
        let waiter = thread::Builder::new()
            .name("t7-r1-waiter".into())
            .spawn_scoped(s, move || {
                done_tx.send(client.execute(&call(), soon())).unwrap();
            })
            .unwrap();
        held.waiting.recv_timeout(Duration::from_secs(2)).unwrap();
        f.clock.0.store(NOW + 3601, Ordering::SeqCst);
        held.release.send(()).unwrap();
        let finished = done.recv_timeout(Duration::from_secs(2));
        let first = first.join().unwrap();
        waiter.join().unwrap();
        (first, finished)
    });
    assert_eq!(first, Err(Error));
    finished
        .expect("failure must notify the waiting caller before its long deadline")
        .expect("the other caller can make its own mint attempt");
    assert_eq!(held.exchange.calls.load(Ordering::SeqCst), 2);
    assert_eq!(f.gh_calls().len(), 1);
    assert_eq!(f.gh_calls()[0]["token"], "synthetic-next-token");
}
