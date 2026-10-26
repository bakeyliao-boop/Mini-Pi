"""python -m mini_pi；仅调用终端入口并传递退出码。"""

from mini_pi.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
