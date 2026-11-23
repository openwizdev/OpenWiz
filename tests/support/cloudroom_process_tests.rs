use super::*;

#[test]
fn the_read_timeout_is_read_timeout_unless_a_fixture_lowers_it() {
    assert_eq!(read_timeout_with(0), READ_TIMEOUT);
    assert_eq!(read_timeout_with(1), Duration::from_millis(1));
    assert_eq!(read_timeout_with(1_000), Duration::from_secs(1));
    assert_eq!(read_timeout_with(15_000), READ_TIMEOUT);
    assert_eq!(read_timeout_with(15_001), READ_TIMEOUT);
    assert_eq!(read_timeout_with(u64::MAX), READ_TIMEOUT);
    assert_eq!(read_timeout(), READ_TIMEOUT);
}

struct OversizedProcess {
    dir: std::path::PathBuf,
    program: std::path::PathBuf,
}

impl OversizedProcess {
    fn new(name: &str) -> Self {
        use std::os::unix::fs::DirBuilderExt;
        let dir = std::env::temp_dir().join(format!("openwiz-2831-{}-{name}", std::process::id()));
        std::fs::DirBuilder::new().mode(0o700).create(&dir).unwrap();
        let program = dir.join("room-cli");
        place_script(
            &program,
            r#"#!/usr/bin/python3 -I
import os, pathlib, time
root = pathlib.Path(__file__).parent
(root / "pid").write_text(str(os.getpid()))
body = bytes(34603010)
try:
    os.write(1, body)
except BrokenPipeError:
    pass
(root / "held").write_text("oversized output attempted; still alive")
while True:
    time.sleep(3600)
"#,
        );
        Self { dir, program }
    }

    fn assert_reaped(&self) {
        let pid = std::fs::read_to_string(self.dir.join("pid")).unwrap();
        assert!(
            !Command::new("kill")
                .args(["-0", &pid])
                .stderr(Stdio::null())
                .status()
                .unwrap()
                .success(),
            "child must be killed and reaped"
        );
    }
}

fn place(src: &Path, dst: &Path) {
    use std::os::unix::fs::PermissionsExt;
    assert!(!dst.is_dir(), "{} is a directory", dst.display());
    let out = Command::new("cp")
        .arg("--")
        .arg(src)
        .arg(dst)
        .stdin(Stdio::null())
        .output()
        .expect("cp runs");
    assert!(
        out.status.success(),
        "cp {}: {}",
        dst.display(),
        String::from_utf8_lossy(&out.stderr)
    );
    std::fs::set_permissions(dst, std::fs::Permissions::from_mode(0o700)).unwrap();
}

fn place_script(dst: &Path, text: &str) {
    let src = dst.with_extension("src");
    std::fs::write(&src, text).unwrap();
    place(&src, dst);
    std::fs::remove_file(src).unwrap();
}

impl Drop for OversizedProcess {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.dir);
    }
}

#[test]
fn an_oversized_read_is_refused_without_waiting_for_child_exit() {
    let fixture = OversizedProcess::new("read");
    let budget = Duration::from_secs(3);
    let began = Instant::now();
    let result = run(
        &fixture.program,
        &Invocation::ThreadList {
            include_hidden: false,
            include_archived: false,
        },
        began + budget,
    );
    fixture.assert_reaped();
    assert_eq!(
        result,
        Err(SourceError::Malformed {
            detail: "printed more than 33554432 bytes".into()
        })
    );
    assert!(
        began.elapsed() < budget,
        "oversized read must refuse before its deadline"
    );
}

#[test]
fn over_cap_writes_keep_waiting_and_are_never_early_malformed() {
    use crate::allowlist::{SpawnArgs, ThreadId};
    use openwiz_core::attachment::{
        AttachmentId, Kind, PromptAttachment, SafeName, Sha256, StagedAttachment, StagedPath,
    };
    use openwiz_core::messaging::Mode;
    let id = ThreadId::parse("thr_syn_2831").unwrap();
    let attachment_id = AttachmentId::parse("att-syn-2831").unwrap();
    let name = SafeName::parse("synthetic.txt").unwrap();
    let attachment = StagedAttachment {
        path: StagedPath::new(Path::new("/synthetic/attachments"), &attachment_id, &name).unwrap(),
        attachment: PromptAttachment {
            id: attachment_id,
            name,
            kind: Kind::File,
            size_bytes: 1,
            sha256: Sha256::parse(&"0".repeat(64)).unwrap(),
        },
    };
    let spawn = SpawnArgs::new(
        "prj_syn_2831",
        "codex",
        "synthetic-model",
        "high",
        "ow1-0123456789abcdef0123456789abcdef01234567",
        "Synthetic prompt",
    )
    .unwrap();
    for (name, invocation) in [
        (
            "tell",
            Invocation::ThreadTell {
                id: id.clone(),
                mode: Mode::Queue,
                text: "Synthetic".into(),
                attachments: vec![],
            },
        ),
        (
            "tell-attachment",
            Invocation::ThreadTell {
                id: id.clone(),
                mode: Mode::Queue,
                text: "Synthetic".into(),
                attachments: vec![attachment.clone()],
            },
        ),
        ("spawn", Invocation::ThreadSpawn(spawn.clone())),
        (
            "spawn-attachment",
            Invocation::ThreadSpawn(spawn.with_attachments(vec![attachment])),
        ),
        ("archive", Invocation::ThreadArchive(id.clone())),
        ("resume", Invocation::LoopResume(id.clone())),
        ("pause", Invocation::LoopPause(id)),
    ] {
        let fixture = OversizedProcess::new(name);
        let result = run(
            &fixture.program,
            &invocation,
            Instant::now() + Duration::from_secs(5),
        );
        assert!(
            matches!(result, Err(SourceError::TimedOut { .. })),
            "{name}: keep the previous timeout outcome, got {result:?}"
        );
        fixture.assert_reaped();
        assert!(
            fixture.dir.join("held").is_file(),
            "{name}: writer must reach held state"
        );
    }
}

#[test]
fn the_response_collector_reads_exactly_the_cap_plus_one() {
    use std::sync::Arc;
    use std::sync::atomic::AtomicUsize;
    struct Counted(Arc<AtomicUsize>);
    impl std::io::Read for Counted {
        fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
            buf.fill(0);
            self.0.fetch_add(buf.len(), Ordering::SeqCst);
            Ok(buf.len())
        }
    }
    let count = Arc::new(AtomicUsize::new(0));
    let bytes = collect(Some(Counted(count.clone())), MAX_STDOUT_BYTES)
        .recv_timeout(Duration::from_secs(3))
        .unwrap();
    assert_eq!(bytes.len(), 33_554_433);
    assert_eq!(count.load(Ordering::SeqCst), 33_554_433);
}
