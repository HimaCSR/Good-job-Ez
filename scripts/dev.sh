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
# 桌面半边独立于 agent 半边 —— agent 半边里不能有 desktop/plugin.js，
# 否则 Hermes 会把它当「统一包的桌面半边」，默认禁用、还要用户手动启用。
DESKTOP_SRC="$REPO_ROOT/src/desktop/job-radar"

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

# ── check ───────────────────────────────────────────────────────────────
cmd_check() {
    say "=== 1/3 单元测试 ==="
    cmd_test || die "测试没过"

    say ""
    say "=== 2/3 脱敏扫描 ==="
    bash "$SCRIPT_DIR/check-sensitive.sh" || die "脱敏扫描没过"

    say ""
    say "=== 3/3 仓库卫生 ==="
    bash "$SCRIPT_DIR/check-repo.sh" || die "仓库卫生检查没过"

    ok "全部检查通过"
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

    # ② 桌面半边
    local dlt
    dlt="$(powershell -NoProfile -Command \
        "(Get-Item '$(winpath "$DESKTOP_COPY")').LinkType" 2>/dev/null | tr -d '\r')"
    if [ "$dlt" = "Junction" ]; then
        ok "桌面半边已是 junction"
    else
        if [ -e "$DESKTOP_COPY" ]; then
            rm -rf "$DESKTOP_COPY" 2>/dev/null || warn "删不掉桌面端副本目录"
        fi
        powershell -NoProfile -Command \
            "cmd /c mklink /J '$(winpath "$DESKTOP_COPY")' '$(winpath "$DESKTOP_SRC")'" >/dev/null 2>&1 \
            || die "桌面半边 mklink 失败"
        ok "桌面半边已建 junction"
    fi

    say ""
    ok "仓库现在是唯一真相源 —— 改代码即生效"
    say "${DIM}桌面端需要重启 Hermes 桌面 app（或 Plugins → Rescan）才会重新加载${OFF}"
    say "${DIM}网关侧建议重启一次：hermes gateway restart${OFF}"
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
    DESKTOP_SRC="$REPO_ROOT/src/desktop/job-radar"

    [ -d "$PLUGIN_DIR" ] || die "找不到 $PLUGIN_DIR"
    [ -f "$DESKTOP_SRC/plugin.js" ] || die "找不到 $DESKTOP_SRC/plugin.js"

    cmd_link

    say ""
    ok "装好了"
    say ""
    say "接下来："
    say "  1. 重启 Hermes 桌面 app —— 设置页 ▸ 插件 里会出现「好岗好找」"
    say "  2. 重启网关，让新的 agent 半边生效：hermes gateway restart"
    say "  3. 设置页里填个人信息、期望城市、技能（还有「真实经历」）"
    say "  4. 平台接入页检查登录态；没登录就在浏览器里登录招聘站"
    say ""
    say "${DIM}桌面端不需要再去 Settings ▸ Plugins 手动启用 —— 装出来就是默认启用${OFF}"
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
