use crate::simple::summarize;

pub fn run_dynamic(name: &str) -> String {
    match name {
        "summarize" => format!("dynamic:{}", summarize()),
        _ => "unknown".to_string(),
    }
}
