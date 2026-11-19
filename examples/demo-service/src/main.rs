use std::env;

fn main() {
    let level = env::var("LOG_LEVEL").unwrap_or_else(|_| "info".to_string());
    println!("level={level}");
}
