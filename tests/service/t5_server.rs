//! The real HTTP lifecycle on loopback, with an unreachable fixture tool.
use super::*;
use std::{
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    sync::{Arc, Mutex, mpsc},
    thread,
};
pub(super) fn server(log: openwiz_server::Log) -> openwiz_server::Server {
    openwiz_server::start(
        TcpListener::bind(("127.0.0.1", 0)).unwrap(),
        openwiz_server::Config::default(),
        Arc::new(CloudRoomSource::new("/synthetic/unreachable-room")),
        Arc::new(openwiz_server::SystemClock),
        log,
    )
    .unwrap()
}
pub(super) fn health(addr: std::net::SocketAddr) -> String {
    let mut connection = TcpStream::connect(addr).unwrap();
    connection.set_read_timeout(Some(RUN_BUDGET)).unwrap();
    write!(
        connection,
        "GET /api/v1/health HTTP/1.1\r\nHost: {addr}\r\nConnection: close\r\n\r\n"
    )
    .unwrap();
    let mut result = String::new();
    connection.read_to_string(&mut result).unwrap();
    result
}
#[test]
fn stopped_server_releases_its_listener_before_replacement() {
    let old = server(Arc::new(|_| {}));
    let addr = old.local_addr();
    assert!(health(addr).starts_with("HTTP/1.1 200"));
    old.shutdown(deadline()).unwrap();
    let listener = TcpListener::bind(addr).expect("old listener must be closed before replacement");
    let replacement = openwiz_server::start(
        listener,
        openwiz_server::Config::default(),
        Arc::new(CloudRoomSource::new("/synthetic/unreachable-room")),
        Arc::new(openwiz_server::SystemClock),
        Arc::new(|_| {}),
    )
    .unwrap();
    assert!(health(addr).starts_with("HTTP/1.1 200"));
    replacement.shutdown(deadline()).unwrap();
    old.join();
    replacement.join();
}
#[test]
fn bounded_shutdown_does_not_claim_drained_while_a_worker_still_runs() {
    let (entered_tx, entered_rx) = mpsc::sync_channel(1);
    let (release_tx, release_rx) = mpsc::sync_channel(1);
    let release = Mutex::new(release_rx);
    let old = server(Arc::new(move |_| {
        entered_tx.send(()).unwrap();
        release.lock().unwrap().recv().unwrap();
    }));
    let addr = old.local_addr();
    let request = thread::spawn(move || health(addr));
    entered_rx.recv_timeout(RUN_BUDGET).unwrap();
    assert!(
        old.shutdown(Instant::now()).is_err(),
        "a running worker cannot count as stopped"
    );
    release_tx.send(()).unwrap();
    assert!(request.join().unwrap().starts_with("HTTP/1.1 200"));
    old.shutdown(deadline()).unwrap();
    old.join();
}
