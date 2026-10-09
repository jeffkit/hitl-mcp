"""文档断言测试：防止 README.md / AGENTS.md 的关键事实与代码漂移。

覆盖审计（docs/DOC_CODE_AUDIT-2026-10-01.md §七「防漂移机制落地」）声称的
5 类守卫。纯文本 / 正则断言，不依赖网络与 Docker。
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
AGENTS = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
BUILTIN_ENGINES = (
    REPO_ROOT / "packages" / "hitl-server" / "hitl_server" / "engines" / "builtin.py"
).read_text(encoding="utf-8")
PYPROJECT = (
    REPO_ROOT / "packages" / "mcp-server-py" / "pyproject.toml"
).read_text(encoding="utf-8")

CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7}

EXPECTED_ENGINES = {"ilink", "wecom-aibot", "telegram", "discord", "feishu"}


def _actual_engine_names() -> set[str]:
    """builtin.py 中 EngineDescriptor(name=...) 声明的引擎名（单一事实源）。"""
    return set(re.findall(r'EngineDescriptor\(\s*\n\s*name="([^"]+)"', BUILTIN_ENGINES))


def _declared_engine_count(text: str, doc: str) -> int:
    """从文档「## N 个内置引擎」标题或「**N 个**引擎」正文解析声明的引擎数。"""
    m = re.search(
        r"##\s*(?:[^\n\d一二两三四五六七八九十]*)([一二两三四五六七八九十\d]+)\s*个内置引擎",
        text,
    ) or re.search(r"\*\*([一二两三四五六七八九十\d]+)\s*个?\*\*引擎", text)
    assert m, f"{doc} 未声明内置引擎数（缺少「N 个内置引擎」标题），请同步文档或本测试的解析规则"
    token = m.group(1)
    return int(token) if token.isdigit() else CN_NUM[token]


def test_engine_count_matches_docs():
    """builtin.py 的 EngineDescriptor 计数 == README / AGENTS 声明的引擎数。"""
    actual = _actual_engine_names()
    expected = len(re.findall(r"EngineDescriptor\(", BUILTIN_ENGINES))
    assert actual == EXPECTED_ENGINES, (
        f"builtin.py 引擎清单与预期不符：{sorted(actual)}（改动引擎清单时请同步更新文档与本测试）"
    )
    for doc, text in (("README.md", README), ("AGENTS.md", AGENTS)):
        declared = _declared_engine_count(text, doc)
        assert declared == expected, (
            f"{doc} 声明 {declared} 个内置引擎，builtin.py 实际有 {expected} 个"
            f"（{sorted(actual)}）"
        )


def test_builtin_descriptors_registry_matches_named_ones():
    """BUILTIN_DESCRIPTORS 列出的每个名字都有对应 descriptor，反之亦然。"""
    named = _actual_engine_names()
    registry_block = re.search(
        r"BUILTIN_DESCRIPTORS\s*=\s*\[(.*?)\]", BUILTIN_ENGINES, re.S
    ).group(1)
    # wecom_descriptor 的 name 是 "wecom-aibot"，注册表变量名仅取连字符前缀
    registered = {n if n != "wecom" else "wecom-aibot" for n in re.findall(r"(\w+)_descriptor", registry_block)}
    assert registered == named, f"注册表 {sorted(registered)} != descriptor 名单 {sorted(named)}"


def test_pypi_package_name_consistent():
    """pyproject 的包名 == 文档 uvx 用的名字；且不再出现错误的 uvx hil-mcp。"""
    m = re.search(r'^name\s*=\s*"([^"]+)"', PYPROJECT, re.M)
    assert m, "mcp-server-py/pyproject.toml 缺少 project.name"
    pkg = m.group(1)
    for doc, text in (("README.md", README), ("AGENTS.md", AGENTS)):
        uvx_pkgs = set(re.findall(r"uvx\s+([a-zA-Z0-9_-]+)", text))
        assert uvx_pkgs <= {pkg}, (
            f"{doc} 出现 uvx {'、'.join(sorted(uvx_pkgs - {pkg}))}，"
            f"PyPI 包名是 {pkg}，照文档装不到"
        )
        assert f"uvx {pkg}" in text, f"{doc} 未提及 uvx {pkg}"


def test_no_bare_database_env_names():
    """文档不得出现裸 USE_DATABASE / DATABASE_URL（正名是 HIL_ 前缀）。"""
    for doc, text in (("README.md", README), ("AGENTS.md", AGENTS)):
        bare = re.findall(r"(?<![A-Z_])(USE_DATABASE|DATABASE_URL)(?![A-Z_])", text)
        assert not bare, f"{doc} 出现裸环境变量名 {sorted(set(bare))}，正名是 HIL_USE_DATABASE / HIL_DATABASE_URL"


def test_no_removed_hil_engine_in_docs():
    """已移除的 hil 引擎不得再出现在引擎清单 / --engine 取值里。"""
    pattern = re.compile(r"--engine\s+(\S+)")
    for doc, text in (("README.md", README), ("AGENTS.md", AGENTS)):
        engines = set(pattern.findall(text))
        assert "hil" not in engines, f"{doc} 仍引用已移除的 hil 引擎"
    m = re.search(r"MCP 引擎类型[：:]\s*`([^`]+)`", AGENTS)
    if m:
        listed = {e.strip() for e in m.group(1).split("/")}
        assert "hil" not in listed, f"AGENTS.md 引擎类型清单仍含 hil：{sorted(listed)}"


def test_readme_agents_engine_lists_consistent():
    """README 与 AGENTS 的引擎清单互不矛盾（表格行与反引号枚举的并差为空）。"""
    names = EXPECTED_ENGINES
    for doc, text in (("README.md", README), ("AGENTS.md", AGENTS)):
        mentioned = set(re.findall(r"`(ilink|wecom-aibot|telegram|discord|feishu)`", text))
        missing = names - mentioned
        stale = mentioned - names
        assert not stale, f"{doc} 提到不存在于 builtin.py 的引擎：{sorted(stale)}"
        assert not missing, f"{doc} 未提到内置引擎：{sorted(missing)}"
