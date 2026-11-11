"""Double-click entry point for the complete existing FastAPI backend."""
import multiprocessing
import os
import sys
import traceback

from runtime_paths import BASE_DIR


def main():
    multiprocessing.freeze_support()
    os.chdir(BASE_DIR)
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    from env_config import ENV_EXAMPLE_TEMPLATE, ENV_PATH, initialize_environment
    if not ENV_PATH.exists():
        ENV_PATH.write_text(ENV_EXAMPLE_TEMPLATE, encoding="utf-8")
    initialize_environment()

    from server_fusion import app, SERVER_HOST, SERVER_PORT
    if "--self-test" in sys.argv:
        import json
        print(json.dumps({"ok": True, "base_dir": str(BASE_DIR),
                          "env_path": str(ENV_PATH), "routes": len(app.routes),
                          "llm_model": os.getenv("LLM_MODEL"),
                          "deepgram_language": os.getenv("DEEPGRAM_LANGUAGE")}, ensure_ascii=False))
        return

    import uvicorn
    from discovery import resolve_lan_ipv4
    port = SERVER_PORT
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    print("\n護理教學後端啟動中，請保持此視窗開啟。")
    print("停止服務：按 Ctrl+C，或關閉視窗。")
    print(f"設定檔：{ENV_PATH}（修改後重新啟動）")
    print(f"報告：http://127.0.0.1:{port}/reports")
    address = resolve_lan_ipv4("192.168.1.1")
    if address:
        print(f"Quest / Unity 連線：http://{address}:{port}")
    uvicorn.run(app, host=SERVER_HOST, port=port, loop="asyncio", http="h11", ws="websockets")


if __name__ == "__main__":
    try:
        main()
    except (Exception, SystemExit) as error:
        if isinstance(error, SystemExit) and not error.code:
            raise
        log_dir = BASE_DIR / "logs"
        log_dir.mkdir(exist_ok=True)
        details = traceback.format_exc()
        with (log_dir / "startup-error.log").open("a", encoding="utf-8") as log:
            log.write(details + "\n")
        print(details)
        print("啟動失敗，請查看 logs/startup-error.log。")
        if sys.stdin is not None and sys.stdin.isatty():
            input("按 Enter 關閉視窗…")
        sys.exit(1)
