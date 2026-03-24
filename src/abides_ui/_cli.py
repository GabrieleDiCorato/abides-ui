import sys
from pathlib import Path


def main() -> None:
    from streamlit.web.cli import main as st_main

    app_path = str(Path(__file__).parent / "app.py")
    sys.argv = ["streamlit", "run", app_path, "--server.headless", "true", *sys.argv[1:]]
    st_main()
