#!/usr/bin/env bash
# 好岗好找 · 开发脚本
#
#   ./scripts/dev.sh test           跑单元测试
#   ./scripts/dev.sh check          提交前检查（测试 + 脱敏 + 仓库卫生）
#   ./scripts/dev.sh sync-desktop   把桌面端 plugin.js 同步到桌面端副本
#   ./scripts/dev.sh link           把插件目录换成 junction 指向仓库（需先停网关）
#   ./scripts/dev.sh unlink         还原成普通目录
#   ./scripts/dev.sh logs           看最近的运行日志
#
# Windows 用 Git Bash 跑：bash scripts/dev.sh test

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLUGIN_DIR="$REPO_ROOT/src/job_radar"

# Hermes 目录：Windows 下在 LOCALAPPDATA，Linux/macOS 下在 ~/.hermes
if [ -n "${LOCALAPPDATA:-}" ]; then
    HERMES_HOME="$LOCALAPPDATA/hermes"
else
    HERMES_HOME="$HOME/.hermes"
fi
RUNTIME_PLUGIN="$HERMES_HOME/plugins/job-radar"
DESKTOP_COPY="$HERMES_HOME/desktop-plugins/job-radar"

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
cmd_sync_desktop() {
    if [ ! -d "$DESKTOP_COPY" ]; then
        warn "桌面端副本目录不存在：$DESKTOP_COPY"
        warn "（桌面端还没 materialize 过？）先在 Hermes 里 Reload desktop plugins"
        return 1
    fi
    cp "$PLUGIN_DIR/desktop/plugin.js" "$DESKTOP_COPY/plugin.js"
    ok "已同步 desktop/plugin.js → 桌面端副本"
    say "${DIM}桌面端有 fs-watch，一般会自动热重载；没反应就点 Plugins → Rescan${OFF}"
}

# ── link / unlink ───────────────────────────────────────────────────────
cmd_link() {
    if [ ! -d "$PLUGIN_DIR" ]; then die "仓库里没有 $PLUGIN_DIR"; fi

    if [ -e "$RUNTIME_PLUGIN" ]; then
        if [ -d "$RUNTIME_PLUGIN.bak-before-junction" ]; then
            rm -rf "$RUNTIME_PLUGIN.bak-before-junction"
        fi
        say "备份当前插件目录…"
        cp -r "$RUNTIME_PLUGIN" "$RUNTIME_PLUGIN.bak-before-junction" 2>/dev/null \
            || warn "备份不完整（可能有文件被占用）"
        rm -rf "$RUNTIME_PLUGIN" 2>/dev/null \
            || die "删不掉插件目录 —— 多半是网关还在跑。先停网关：hermes gateway stop"
    fi

    say "建 junction：$RUNTIME_PLUGIN → $PLUGIN_DIR"
    if command -v mklink >/dev/null 2>&1; then
        cmd.exe //c "mklink /J \"$(cygpath -w "$RUNTIME_PLUGIN")\" \"$(cygpath -w "$PLUGIN_DIR")\"" \
            || die "mklink 失败"
    else
        ln -s "$PLUGIN_DIR" "$RUNTIME_PLUGIN" || die "ln -s 失败"
    fi
    ok "已建链接。重启网关后生效：hermes gateway restart"
}

cmd_unlink() {
    if [ ! -d "$RUNTIME_PLUGIN.bak-before-junction" ]; then
        die "没有备份可还原：$RUNTIME_PLUGIN.bak-before-junction"
    fi
    rm -rf "$RUNTIME_PLUGIN" 2>/dev/null \
        || die "删不掉插件目录 —— 先停网关"
    cp -r "$RUNTIME_PLUGIN.bak-before-junction" "$RUNTIME_PLUGIN"
    ok "已还原成普通目录"
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
    logs)           shift; cmd_logs "$@" ;;
    help|-h|--help)
        say "用法: bash scripts/dev.sh <命令>"
        say ""
        say "  test           跑单元测试"
        say "  check          提交前检查（测试 + 脱敏 + 仓库卫生）"
        say "  sync-desktop   同步桌面端 plugin.js"
        say "  link           插件目录换成 junction 指向仓库（需先停网关）"
        say "  unlink         还原成普通目录"
        say "  logs [N|-f]    看运行日志"
        ;;
    *) die "未知命令：$1（试试 $0 help）" ;;
esac
