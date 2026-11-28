use serde_json::Value;

const INVALID: &str = "the report or the baseline could not be read";

pub fn check(report: &Value, baseline: &Value) -> Result<(), String> {
    let overall = &report["overall"];
    let latency = match overall.get("p90_latency_ms") {
        None | Some(Value::Null) => None,
        Some(value) => Some(value.as_f64().ok_or(INVALID)?),
    };
    let acceptance = number(overall, "acceptance_rate")?;
    let saved = number(overall, "chars_saved_per_message")?;
    let limit = number(baseline, "p90_latency_ms_max")?;
    let acceptance_min = number(baseline, "acceptance_rate_min")?;
    let saved_min = number(baseline, "chars_saved_per_message_min")?;

    if let Some(latency) = latency
        && latency > limit
    {
        return Err(format!("p90 {latency} ms is above {limit} ms"));
    }
    if acceptance < acceptance_min {
        return Err(format!(
            "acceptance {acceptance} is below the baseline {acceptance_min}"
        ));
    }
    if saved < saved_min {
        return Err(format!(
            "characters saved per message {saved} is below the baseline {saved_min}"
        ));
    }
    Ok(())
}

fn number(object: &Value, key: &str) -> Result<f64, String> {
    object[key].as_f64().ok_or_else(|| INVALID.to_owned())
}
