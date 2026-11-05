//! #373: external failure answers, shared by the two public CLI proofs.

use serde_json::{Value, json};

/// Each differs from the one approved response; none is an empty read.
pub(crate) fn failures() -> Vec<Value> {
    let exact = "no checks reported on the 'room/syn-2' branch\n";
    let mut cases = vec![
        json!({"exit": 2, "stderr": exact}),
        json!({"exit": 8, "stderr": exact}),
        json!({"exit": 1, "stdout": "[]", "stderr": exact}),
        json!({"exit": 1, "stdout": " ", "stderr": exact}),
        json!({"exit": 1, "stderr": ""}),
        json!({"exit": 1, "stderr": "authentication required\n"}),
        json!({"exit": 1, "stderr": "network unreachable\n"}),
        json!({"exit": 1, "stderr": "HTTP 403: synthetic refusal\n"}),
    ];
    for text in [
        "no checks reported on the 'room/syn-2' branch",
        "no checks reported on the 'room/syn-2' branch\r\n",
        "no checks reported on the 'room/syn-2' branch\n\n",
        "no checks reported on the 'room/syn-2' branch\nHTTP 403\n",
        "warning\nno checks reported on the 'room/syn-2' branch\n",
        " no checks reported on the 'room/syn-2' branch\n",
        "no checks reported on the 'room/syn-2' branch \n",
        "No checks reported on the 'room/syn-2' branch\n",
        "no required checks reported on the 'room/syn-2' branch\n",
        "no checks reported on the \"room/syn-2\" branch\n",
        "no checks reported on the '' branch\n",
        "no checks reported on the 'room/syn-☃' branch\n",
        "no checks reported on the 'room/syn 2' branch\n",
        "no checks reported on the 'room/syn-2\n' branch\n",
        "no checks reported on the 'room/syn-2\u{1b}[31m' branch\n",
        "no checks reported on the 'room/../syn-2' branch\n",
    ] {
        cases.push(json!({"exit": 1, "stderr": text}));
    }
    cases
}
