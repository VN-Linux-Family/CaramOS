//! caramos-business-agent: the employee machine's agent of CaramOS Doanh nghiệp (see lib.rs and ../PROTOCOL.md).

use std::process::ExitCode;

use caramos_business_agent::{daemon, process, session};

const USAGE: &str = "\
Usage: caramos-business-agent daemon | session | leave

  daemon   the service (root, caramos-business-agent.service): takes the admin's signed
           policy, applies the system settings, runs the signed commands, reports back
  session  in each user's session (autostart): applies the user's settings and shows the
           messages, countdowns and remote help requests
  leave    (root) the machine leaves the company: stops the service and puts back
           everything the agent changed, the users' part through their session parts
";

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.iter().map(String::as_str).collect::<Vec<_>>().as_slice() {
        ["daemon"] => {
            if process::uid() != Some(0) {
                eprintln!("caramos-business-agent daemon runs as root (caramos-business-agent.service)");
                return ExitCode::FAILURE;
            }
            daemon::main()
        }
        ["session"] => session::main(),
        ["leave"] => {
            if process::uid() != Some(0) {
                eprintln!("caramos-business-agent leave runs as root");
                return ExitCode::FAILURE;
            }
            daemon::leave_main()
        }
        ["-h" | "--help"] => {
            print!("{USAGE}");
            ExitCode::SUCCESS
        }
        ["--version"] => {
            println!("caramos-business-agent {}", env!("CARGO_PKG_VERSION"));
            ExitCode::SUCCESS
        }
        _ => {
            eprint!("{USAGE}");
            ExitCode::from(2)
        }
    }
}
