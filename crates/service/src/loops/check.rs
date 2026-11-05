//! A check's deadline covers exit and EOF, including inherited stdout pipes.
use openwiz_core::{messaging::MAX_TEXT_BYTES, ops::Clock};
use serde_json::{Value, json};
use std::{
    io::Read,
    os::unix::process::CommandExt,
    path::Path,
    process::{Command, Stdio},
    sync::mpsc,
    thread,
    time::Duration,
};

pub fn run(root: &Path, check: &Value, clock: &dyn Clock) -> Value {
    let argv = check["argv"].as_array().unwrap();
    let Some(deadline) = clock
        .monotonic()
        .checked_add(Duration::from_millis(check["timeout_ms"].as_u64().unwrap()))
    else {
        return failed();
    };
    let mut child = match Command::new(argv[0].as_str().unwrap())
        .args(argv[1..].iter().map(|s| s.as_str().unwrap()))
        .current_dir(root)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .process_group(0)
        .spawn()
    {
        Ok(child) => child,
        Err(_) => return failed(),
    };
    let mut pipe = child
        .stdout
        .take()
        .unwrap()
        .take((MAX_TEXT_BYTES + 1) as u64);
    let (sender, receiver) = mpsc::channel();
    let reader = thread::spawn(move || {
        let mut bytes = Vec::new();
        let result = pipe.read_to_end(&mut bytes).map(|_| bytes);
        let _ = sender.send(result);
    });
    let mut output = None;
    let mut status = None;
    let result = loop {
        if clock.monotonic() >= deadline {
            break json!({"kind":"check_timed_out"});
        }
        if output.is_none() {
            match receiver.try_recv() {
                Ok(Ok(bytes)) if bytes.len() > MAX_TEXT_BYTES => {
                    break json!({"kind":"check_failed","reason":"Check stdout exceeds the 16 KiB limit."});
                }
                Ok(result) => output = Some(result),
                Err(mpsc::TryRecvError::Empty) => {}
                Err(_) => break failed(),
            }
        }
        if status.is_none() {
            match child.try_wait() {
                Ok(result) => status = result,
                Err(_) => break failed(),
            }
        }
        if let (Some(status), Some(output)) = (&status, &output) {
            break if !status.success() {
                failed()
            } else {
                match output {
                    Ok(bytes) if bytes.is_empty() => json!({"kind":"quiet"}),
                    Ok(bytes) => match std::str::from_utf8(bytes) {
                        Ok(s) if !s.contains('\0') => {
                            json!({"kind":"deferred","finding":s,"reason":"Awaiting dispatch admission."})
                        }
                        _ => failed(),
                    },
                    Err(_) => failed(),
                }
            };
        }
        thread::park_timeout(Duration::from_millis(2));
    };
    // Only this check's process group: descendants retaining its pipes must
    // stop too. Never signal the service or another job's group.
    let _ = Command::new("/bin/kill")
        .args(["-KILL", "--", &format!("-{}", child.id())])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
    let _ = child.kill();
    let _ = child.wait();
    // A check may deliberately detach a descendant. Do not let that hold
    // the scheduler beyond its deadline waiting for a pipe-reader thread.
    if reader.is_finished() {
        let _ = reader.join();
    }
    result
}
fn failed() -> Value {
    json!({"kind":"check_failed","reason":"Check could not complete successfully with valid UTF-8 output."})
}
