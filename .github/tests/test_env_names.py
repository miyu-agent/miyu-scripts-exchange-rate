# exchange_rate.py 读新环境变量名的测试（审计 2026-11-18 #168）。
#
# 跑法（在仓库根）：
#   python3 -I -B -m unittest discover -s .github/tests
# （不加 -t .：.github 不是合法的包名，加了 unittest 会报 Start directory is not importable。）
#
# 只用标准库；不联网：get_json 换成桩，断网也能跑。HOME、XDG_*、MIYU_* 都指到临时目录。
# 放在 .github/tests/ 而不是 tests/：打包会跳过 .github，测试不会进包。

import importlib.util
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "exchange_rate.py"


def load():
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("exchange_rate_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Sandbox(unittest.TestCase):
    """每条测试一个临时目录，环境里去掉所有 MIYU_*，网络函数先换成直接失败的桩。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = pathlib.Path(self.tmp.name)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("MIYU_", "XDG_"))}
        env.update(HOME=str(root / "home"), XDG_CONFIG_HOME=str(root / "cfg"),
                   XDG_CACHE_HOME=str(root / "xdg-cache"), XDG_STATE_HOME=str(root / "xdg-state"),
                   XDG_DATA_HOME=str(root / "xdg-data"))
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.root = root
        self.mod = load()
        self.calls = []

        def no_network(url, host):
            self.calls.append(url)
            raise AssertionError(f"测试里不该联网：{url}")

        self.mod.get_json = no_network

    def call(self, args):
        """照 main() 跑一次：stdin 喂 JSON，返回 (退出码, 输出)。"""
        out = io.StringIO()
        code = 0
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(args))), redirect_stdout(out):
            try:
                self.mod.main()
            except SystemExit as exc:
                code = exc.code or 0
        return code, out.getvalue()


class EnvNames(Sandbox):
    # 审计 #168：核心 FH-6 以后只给新名字 MIYU_CACHE_DIR，不再给 MIYU_SCRIPT_CACHE_DIR。
    # 只设新名字时，汇率表应缓存进 MIYU_CACHE_DIR。现在脚本只读旧名，缓存目录是 None，什么都不写。
    def test_cache_goes_to_new_env_name(self):
        cache = self.root / "cache"
        cache.mkdir()
        os.environ["MIYU_CACHE_DIR"] = str(cache)
        self.assertNotIn("MIYU_SCRIPT_CACHE_DIR", os.environ)

        def fake_get_json(url, host):
            self.calls.append(url)
            return [{"quote": "JPY", "rate": 150.25, "date": "2026-11-17"}]

        self.mod.get_json = fake_get_json
        code, out = self.call({"base": "USD", "target": "JPY"})
        self.assertEqual(code, 0, out)
        self.assertTrue((cache / "frankfurter-USD-latest.json").is_file(),
                        f"MIYU_CACHE_DIR 里没有缓存文件：{sorted(os.listdir(cache))}")
        # 第二次应命中缓存，不再联网。
        self.calls.clear()
        code, out = self.call({"base": "USD", "target": "JPY"})
        self.assertEqual(code, 0, out)
        self.assertEqual(self.calls, [], "缓存在 MIYU_CACHE_DIR 里，第二次不该再联网")


if __name__ == "__main__":
    unittest.main()
