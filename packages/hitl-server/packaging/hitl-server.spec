# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for HITL Server（个人端，仅 iLink + WeCom AI 内置引擎）
#
# 用法（在 packages/hitl-server 下执行）：
#   pnpm --dir hitl_server/console run build         # 先构建管理台 dist
#   pyinstaller packaging/hitl-server.spec --distpath dist --workpath build --noconfirm
#
# 产物：dist/hitl-server/  （one-dir，可整体打包发布）
#   运行：dist/hitl-server/hitl-server（读环境变量；默认监听 127.0.0.1:8081）
#
# 说明：
#   - 内嵌 hitl_server/console/dist，管理台随二进制一起分发
#   - 排除 pigeon / fly_pigeon（历史 direct 模式依赖，现已不在依赖中；保留排除项作防御）
#   - one-dir 而非 one-file：启动快、调试友好；brew/deb/rpm 安装时整体拷入

import os
from pathlib import Path

SPECPATH = Path(SPECPATH).resolve()          # packaging/
PKG_ROOT = SPECPATH.parent                    # packages/hitl-server/
MODULE = PKG_ROOT / "hitl_server"
CONSOLE_DIST = MODULE / "console" / "dist"

datas = []
if CONSOLE_DIST.exists():
    datas.append((str(CONSOLE_DIST), str(Path("hitl_server") / "console" / "dist")))
else:
    raise SystemExit(
        f"管理台 dist 不存在: {CONSOLE_DIST}\n"
        f"请先在 hitl_server/console 下执行 pnpm run build。"
    )

hiddenimports = [
    # uvicorn 子模块（PyInstaller 默认收集不全）
    "uvicorn.logging",
    "uvicorn.protocols",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    # 数据库驱动（按需加载，PyInstaller 静态分析看不到）
    "aiosqlite",
    "aiomysql",
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.sqlite.aiosqlite",
    "sqlalchemy.dialects.mysql",
    "sqlalchemy.dialects.mysql.aiomysql",
    # 其它
    "websockets",
    "httpx",
    "jwt",
    "multipart",
    "email_validator",
]

excludes = [
    "pigeon",
    "fly_pigeon",
    "matplotlib",
    "pandas",
    "numpy",
    "scipy",
    "pytest",
]

a = Analysis(
    [str(MODULE / "__main__.py")],
    pathex=[str(PKG_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="hitl-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="hitl-server",
)
