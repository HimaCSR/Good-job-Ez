#!/usr/bin/env bash
# 好岗好找 · 开发脚本
#
#   ./scripts/dev.sh test           跑单元测试
#   ./scripts/dev.sh check          提交前检查（测试 + 脱敏 + 仓库卫生）
#   ./scripts/dev.sh sync-desktop   同步桌面端 plugin.js（junction 模式下是 no-op）
#   ./scripts/dev.sh link           插件目录换成 junction 指向仓库（仓库即真相源）
#   ./scripts/dev.sh unlink         还原成普通目录
#   ./scripts/dev.sh install <路径>  新设备一条命令装好
#   ./scripts/dev.sh logs           看最近的运行日志
#
# Windows 用 Git Bash 跑：bash scripts/dev.sh test

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLUGIN_DIR="$REPO_ROOT/src/job_radar"
# 桌面半边在 agent 半边里（Hermes 的「统一包」形态）。
# 代价：桌面端默认禁用，要去 Settings ▸ Plugins 手动开一次；
# 好处：一个开关管两半、Plugins 页里配对显示、卸载会连带清理。
DESKTOP_SRC="$PLUGIN_DIR/desktop"

# Hermes 目录：Windows 下在 LOCALAPPDATA，Linux/macOS 下在 ~/.hermes
if [ -n "${LOCALAPPDATA:-}" ]; then
    HERMES_HOME="$LOCALAPPDATA/hermes"
else
    HERMES_HOME="$HOME/.hermes"
fi
RUNTIME_PLUGIN="$HERMES_HOME/plugins/job-radar"
DESKTOP_COPY="$HERMES_HOME/desktop-plugins/job-radar"

# MSYS 路径（/d/移动云盘...）PowerShell 不认 —— 传给 Windows 命令前先转。
# cygpath 在 Git Bash 里都有；没有就原样返回（macOS/Linux 用软链，不走这条）。
winpath() {
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -w "$1"
    else
        printf '%s' "$1"
    fi
}

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; DIM=$'\033[2m'; OFF=$'\033[0m'
say()  { printf '%s\n' "$*"; }
ok()   { printf '%s✔%s %s\n' "$GREEN" "$OFF" "$*"; }
warn() { printf '%s!%s %s\n' "$YELLOW" "$OFF" "$*"; }
die()  { printf '%s�’%s %s\n' "$RED" "$OFF" "$*" >&2; exit 1; }

# ── test ────────────────────────────────────────────────────────────────
cmd_test() {
    say "跑单元测试…"
    ( cd "$PLUGIN_DIR" && python -m unittest discover -s tests "$@" ) \
        || die "测试没过"
}

# ── check ────────────────────────────────────────────────────────────────
cmd_check() {
    say "=== 1/7 单元测试 ==="
    cmd_test || die "测试没过"

    say ""
    say "=== 2/7 桌面端 JS 语法 ==="
    cmd_check_desktop_js || die "桌面端 JS 语法不对"

    say ""
    say "=== 3/7 桌面端 CSS 类存在性 ==="
    cmd_check_desktop_css || die "桌面端用了 app CSS 里不存在的类（样式会静默失效）"

    say ""
    say "=== 4/7 桌面端 jsx children 位置 ==="
    cmd_check_jsx_children || die "桌面端把 children 传到了第三个参数（React 当成 key → UI 不渲染）"

    say ""
    say "=== 5/7 脱敏扫描 ==="
    bash "$SCRIPT_DIR/check-sensitive.sh" || die "脱敏扫描没过"

    say ""
    say "=== 6/7 桌面端表单交互 ==="
    cmd_check_form_input || die "桌面端表单输入有问题（打字打不进去 / 技能加不上）"

    say ""
    say "=== 7/7 仓库卫生 ==="
    bash "$SCRIPT_DIR/check-repo.sh" || die "仓库卫生检查没过"

    ok "全部检查通过"
}

# 桌面端 plugin.js 用的 Tailwind 类，**必须在 app 的 CSS 里真的存在**。
#
# **为什么**：Hermes 桌面 app 的 CSS 是 Tailwind JIT 生成的，
# 只包含 app 自己源码里出现过的类。插件是磁盘上未编译的 ESM，
# 它的 className 不在 Tailwind 的扫描范围里 ——
# 写一个 app 没用过的类（比如 max-w-5xl），
# **那个类在 app CSS 里根本不存在** → 样式静默失效，
# 不报错、不警告，只是「看起来不对」。
#
# app.css 在 Hermes 安装目录里，路径随版本变（index-<hash>.css），
# 所以用 glob 找最新的那个。找不到就跳过（别的机器上没装 app）。
# 桌面端 jsx 的 children **必须写在 props 里** ——
# jsx(type, props, key) 的第三个参数是 key，不是 children。
# 写成 jsx('div', {...}, child) → child 变成 key → div 没有 children
# → **那段 UI 根本不渲染，而且不报错**。
cmd_check_jsx_children() {
    local checker="$SCRIPT_DIR/check-jsx-children.mjs"
    local target="$PLUGIN_DIR/desktop/plugin.js"
    [ -f "$checker" ] || { warn "找不到 check-jsx-children.mjs，跳过"; return 0; }
    [ -f "$target" ] || { warn "找不到 desktop/plugin.js，跳过"; return 0; }

    local node_exe=""
    if [ -n "${LOCALAPPDATA:-}" ]; then
        local candidate="$LOCALAPPDATA/hermes/tools/node-26.7.0-win32-x64/node.exe"
        [ -x "$candidate" ] && node_exe="$candidate"
    fi
    [ -z "$node_exe" ] && node_exe="$(command -v node || true)"
    if [ -z "$node_exe" ]; then
        warn "找不到 node，跳过桌面端 jsx 检查"
        return 0
    fi

    local checker_arg="$checker"
    local target_arg="$target"
    if command -v cygpath >/dev/null 2>&1; then
        checker_arg="$(cygpath -w "$checker")"
        target_arg="$(cygpath -w "$target")"
    fi
    "$node_exe" "$checker_arg" "$target_arg" || return 1
}

# 桌面端表单的**真实交互**验证 ——
# 用 jsdom + React 真的渲染 ProfileView，真的打字。
#
# **为什么必须这样测**：
# 「输入框打不进字」这类问题在代码层完全看不出来 ——
# JS 语法对、React 对、onChange 也确实被调用了，
# 但值就是进不去（`setIdentity` 把函数当键名传给了 `set`）。
cmd_check_form_input() {
    local checker="$SCRIPT_DIR/verify-form-input.mjs"
    local target="$PLUGIN_DIR/desktop/plugin.js"
    [ -f "$checker" ] || { warn "找不到 verify-form-input.mjs，跳过"; return 0; }
    [ -f "$target" ] || { warn "找不到 desktop/plugin.js，跳过"; return 0; }

    local node_exe=""
    if [ -n "${LOCALAPPDATA:-}" ]; then
        local candidate="$LOCALAPPDATA/hermes/tools/node-26.7.0-win32-x64/node.exe"
        [ -x "$candidate" ] && node_exe="$candidate"
    fi
    [ -z "$node_exe" ] && node_exe="$(command -v node || true)"
    if [ -z "$node_exe" ]; then
        warn "找不到 node，跳过桌面端表单检查"
        return 0
    fi

    local checker_arg="$checker"
    local target_arg="$target"
    if command -v cygpath >/dev/null 2>&1; then
        checker_arg="$(cygpath -w "$checker")"
        target_arg="$(cygpath -w "$target")"
    fi
    "$node_exe" "$checker_arg" "$target_arg" || return 1
}

cmd_check_desktop_css() {
    local node_bin="$PLUGIN_DIR/desktop/plugin.js"
    local checker="$SCRIPT_DIR/check-desktop-css.mjs"
    [ -f "$node_bin" ] || { warn "找不到 desktop/plugin.js，跳过"; return 0; }
    [ -f "$checker" ] || { warn "找不到 check-desktop-css.mjs，跳过"; return 0; }

    local node_exe=""
    if [ -n "${LOCALAPPDATA:-}" ]; then
        local candidate="$LOCALAPPDATA/hermes/tools/node-26.7.0-win32-x64/node.exe"
        [ -x "$candidate" ] && node_exe="$candidate"
    fi
    [ -z "$node_exe" ] && node_exe="$(command -v node || true)"
    if [ -z "$node_exe" ]; then
        warn "找不到 node，跳过桌面端 CSS 检查"
        return 0
    fi

    # 找 app 的 CSS：apps/desktop/release/win-unpacked/resources/
    #                app.asar.unpacked/dist/assets/index-*.css
    local app_css=""
    if [ -n "${LOCALAPPDATA:-}" ]; then
        app_css="$(ls -t "$LOCALAPPDATA"/hermes/hermes-agent/apps/desktop/release/win-unpacked/resources/app.asar.unpacked/dist/assets/index-*.css 2>/dev/null | head -1)"
    fi
    if [ -z "$app_css" ] || [ ! -f "$app_css" ]; then
        warn "找不到 Hermes 桌面端的 CSS，跳过（CI 上没有 app 安装）"
        return 0
    fi

    local checker_arg="$checker"
    local target_arg="$node_bin"
    local css_arg="$app_css"
    if command -v cygpath >/dev/null 2>&1; then
        checker_arg="$(cygpath -w "$checker")"
        target_arg="$(cygpath -w "$node_bin")"
        css_arg="$(cygpath -w "$app_css")"
    fi
    "$node_exe" "$checker_arg" "$target_arg" "$css_arg" || return 1
}

# 桌面端 plugin.js 是**纯 ESM 未编译**的，改坏了不会报错，只是不渲染。
# 这里做语法自检（只解析，不执行 —— 它 import 的 @hermes/plugin-sdk
# 在插件目录外，直接 import 会失败）。
cmd_check_desktop_js() {
    local node_bin="$PLUGIN_DIR/desktop/plugin.js"
    local checker="$SCRIPT_DIR/check-desktop-js.mjs"
    [ -f "$node_bin" ] || { warn "找不到 desktop/plugin.js，跳过"; return 0; }
    [ -f "$checker" ] || { warn "找不到 check-desktop-js.mjs，跳过"; return 0; }

    # node 优先用 Hermes 自带的（PATH 里的可能是 14）
    local node_exe=""
    if [ -n "${LOCALAPPDATA:-}" ]; then
        local candidate="$LOCALAPPDATA/hermes/tools/node-26.7.0-win32-x64/node.exe"
        [ -x "$candidate" ] && node_exe="$candidate"
    fi
    [ -z "$node_exe" ] && node_exe="$(command -v node || true)"
    if [ -z "$node_exe" ]; then
        warn "找不到 node，跳过桌面端 JS 语法检查"
        return 0
    fi

    # **路径要转成 Windows 格式** —— node 是原生 Windows 程序，
    # 不认 MSYS 的 /盘符/… 路径（会拼成一个不存在的绝对路径，
    # 直接 MODULE_NOT_FOUND）。
    local checker_arg="$checker"
    local target_arg="$node_bin"
    if command -v cygpath >/dev/null 2>&1; then
        checker_arg="$(cygpath -w "$checker")"
        target_arg="$(cygpath -w "$node_bin")"
    fi
    "$node_exe" "$checker_arg" "$target_arg" || return 1
}

# ── sync-desktop ────────────────────────────────────────────────────────
# junction 模式下桌面端直接读仓库的 desktop/plugin.js —— 不用同步。
cmd_sync_desktop() {
    local lt
    lt="$(powershell -NoProfile -Command \
        "(Get-Item '$DESKTOP_COPY').LinkType" 2>/dev/null | tr -d '\r')"
    if [ "$lt" = "Junction" ]; then
        ok "桌面端是 junction → 仓库即运行副本，不用同步"
        say "${DIM}改完 desktop/plugin.js 保存即生效${OFF}"
        return 0
    fi
    if [ ! -d "$DESKTOP_COPY" ]; then
        warn "桌面端副本目录不存在：$DESKTOP_COPY"
        warn "先跑 dev.sh link，或者在 Hermes 里 Reload desktop plugins"
        return 1
    fi
    cp "$DESKTOP_SRC/plugin.js" "$DESKTOP_COPY/plugin.js"
    ok "已同步 desktop/plugin.js → 桌面端副本"
    say "${DIM}桌面端有 fs-watch，一般会自动热重载；没反应就点 Plugins → Rescan${OFF}"
}

# ── link / unlink ───────────────────────────────────────────────────────
#
# 目的：让**仓库成为唯一真相源** —— 改代码即生效，不用手工同步。
#
# 两处都要 junction：
#   <hermes>/plugins/job-radar        → 仓库 src/job_radar      （agent 半边）
#   <hermes>/desktop-plugins/job-radar → 仓库 src/desktop/job-radar（桌面半边）
#
# 备份**不能放在 plugins/ 里** —— 桌面端会扫 plugins/ 下的每个目录，
# 一个残留备份就会触发 "duplicate id" 加载失败。
BACKUP_ROOT="$HERMES_HOME/plugin-backups"

cmd_link() {
    if [ ! -d "$PLUGIN_DIR" ]; then die "仓库里没有 $PLUGIN_DIR"; fi
    mkdir -p "$BACKUP_ROOT"

    # ① agent 半边
    local lt
    lt="$(powershell -NoProfile -Command \
        "(Get-Item '$(winpath "$RUNTIME_PLUGIN")').LinkType" 2>/dev/null | tr -d '\r')"
    if [ "$lt" = "Junction" ]; then
        ok "agent 半边已是 junction"
    else
        if [ -e "$RUNTIME_PLUGIN" ]; then
            say "备份当前插件目录 → $BACKUP_ROOT/…"
            rm -rf "$BACKUP_ROOT/job-radar.bak-pre-junction"
            cp -r "$RUNTIME_PLUGIN" "$BACKUP_ROOT/job-radar.bak-pre-junction" 2>/dev/null \
                || warn "备份不完整（可能有文件被占用）"
            rm -rf "$RUNTIME_PLUGIN" 2>/dev/null \
                || die "删不掉插件目录 —— 先停网关：hermes gateway stop"
        fi
        say "建 junction：plugins/job-radar → 仓库 src/job_radar"
        powershell -NoProfile -Command \
            "cmd /c mklink /J '$(winpath "$RUNTIME_PLUGIN")' '$(winpath "$PLUGIN_DIR")'" >/dev/null 2>&1 \
            || die "agent 半边 mklink 失败"
        ok "agent 半边已建 junction"
    fi

    # ② 桌面半边：普通目录 + 同步（不是 junction）
    #
    # Hermes 的「统一包」形态：agent 半边在 plugins/<name>/，
    # 桌面半边由 Electron 从 plugins/<name>/desktop/ **复制**到
    # desktop-plugins/<name>/，并盖上 .hermes-package.json marker。
    #
    # 桌面端必须是**副本** —— 它要带 marker 才会被认成统一包的半边，
    # 也才会跟 agent 行配对显示、共用一个开关。
    if [ ! -f "$DESKTOP_SRC/plugin.js" ]; then
        die "找不到 $DESKTOP_SRC/plugin.js"
    fi
    mkdir -p "$DESKTOP_COPY"
    cp "$DESKTOP_SRC/plugin.js" "$DESKTOP_COPY/plugin.js"
    ok "桌面半边已同步"

    say ""
    ok "agent 半边改代码即生效（junction）"
    say "${DIM}桌面半边是副本：改完跑 bash scripts/dev.sh sync-desktop${OFF}"
    say "${DIM}桌面端需要重启 Hermes 桌面 app（或 Plugins → Rescan）才会重新加载${OFF}"
    say "${DIM}网关侧建议重启一次：hermes gateway restart${OFF}"
    say ""
    warn "桌面端默认禁用 —— 去 Settings ▸ Plugins 把「好岗好找」打开一次"
}

cmd_unlink() {
    local backup="$BACKUP_ROOT/job-radar.bak-pre-junction"
    [ -d "$backup" ] || die "没有备份可还原：$backup"

    # 拆 junction（不是删内容）
    [ -e "$RUNTIME_PLUGIN" ] && rm -rf "$RUNTIME_PLUGIN" 2>/dev/null
    cp -r "$backup" "$RUNTIME_PLUGIN"
    ok "agent 半边已还原成普通目录"

    if [ -e "$DESKTOP_COPY" ]; then
        rm -rf "$DESKTOP_COPY" 2>/dev/null
        mkdir -p "$DESKTOP_COPY"
        [ -f "$DESKTOP_SRC/plugin.js" ] \
            && cp "$DESKTOP_SRC/plugin.js" "$DESKTOP_COPY/plugin.js"
        ok "桌面半边已还原成普通目录"
    fi
}

# ── install ──────────────────────────────────────────────────────────────
# 新设备一条命令装好：
#   克隆仓库 → agent 半边 + 桌面半边都建 junction → 打印后续步骤。
#
# 桌面半边装成**独立插件**（不是统一包的一半）→ Hermes 不会给它盖
# .hermes-package.json marker → 桌面端默认启用，不用手动去设置里开。
cmd_install() {
    local src="${1:-}"

    if [ -z "$src" ]; then
        die "用法：dev.sh install <仓库路径或 git URL>"
    fi

    # ① 克隆（给的是 URL 就 clone，是本地路径就直接用）
    if [ -d "$src/.git" ] || [ -f "$src/plugin.yaml" ] || [ -d "$src/src/job_radar" ]; then
        REPO_ROOT="$(cd "$src" && pwd)"
        say "用本地仓库：$REPO_ROOT"
    else
        local dest="$HOME/Good-job-Ez"
        if [ -d "$dest" ]; then
            REPO_ROOT="$dest"
        else
            say "克隆 $src → $dest"
            git clone "$src" "$dest" || die "clone 失败"
            REPO_ROOT="$dest"
        fi
    fi

    PLUGIN_DIR="$REPO_ROOT/src/job_radar"
    DESKTOP_SRC="$PLUGIN_DIR/desktop"

    [ -d "$PLUGIN_DIR" ] || die "找不到 $PLUGIN_DIR"
    [ -f "$DESKTOP_SRC/plugin.js" ] || die "找不到 $DESKTOP_SRC/plugin.js"

    cmd_link

    say ""
    ok "装好了"
    say ""
    say "接下来："
    say "  1. 重启 Hermes 桌面 app"
    say "  2. 重启网关，让新的 agent 半边生效：hermes gateway restart"
    say "  3. 设置页里填个人信息、期望城市、技能（还有「真实经历」）"
    say "  4. 平台接入页检查登录态；没登录就在浏览器里登录招聘站"
    say ""
    warn "桌面端默认禁用 —— 去 Settings ▸ Plugins 把「好岗好找」打开一次（只需一次）"
}

# ── logs ────────────────────────────────────────────────────────────────
cmd_logs() {
    local logfile
    logfile="$(cygpath -u "$HERMES_HOME" 2>/dev/null)/plugin-data/job-radar/logs/job-radar.log"
    [ -f "$logfile" ] || die "还没有日志文件：$logfile"
    if [ "${1:-}" = "-f" ]; then
        tail -f "$logfile"
    else
        tail -n "${1:-50}" "$logfile"
    fi
}

# ── 入口 ────────────────────────────────────────────────────────────────
case "${1:-help}" in
    test)           shift; cmd_test "$@" ;;
    check)          cmd_check ;;
    sync-desktop)   cmd_sync_desktop ;;
    link)           cmd_link ;;
    unlink)         cmd_unlink ;;
    install)        shift; cmd_install "$@" ;;
    logs)           shift; cmd_logs "$@" ;;
    help|-h|--help)
        say "用法: bash scripts/dev.sh <命令>"
        say ""
        say "  test           跑单元测试"
        say "  check          提交前检查（测试 + 脱敏 + 仓库卫生）"
        say "  sync-desktop   同步桌面端 plugin.js"
        say "  link           插件目录换成 junction 指向仓库"
        say "  unlink         还原成普通目录"
        say "  install <路径>  新设备一条命令装好（克隆 + 建链接）"
        say "  logs [N|-f]    看运行日志"
        ;;
    *) die "未知命令：$1（试试 $0 help）" ;;
esac
