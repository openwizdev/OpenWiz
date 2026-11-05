fn main() -> std::process::ExitCode {
    openwiz_service::dispatch(openwiz_adapter_cloudroom::locate::Discovery::system())
}
