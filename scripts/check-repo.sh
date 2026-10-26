#!/usr/bin/env bash
# 仓库卫生检查：不该进版本库的东西在不在。
#
# 用法：bash scripts/check-repo.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; OFF=$'\033[0m'
FAIL=0

ok()   { printf '%s✔%s %s\n' "$GREEN" "$OFF" "$*"; }
bad()  { printf '%s✘%s %s\n' "$RED" "$OFF" "$*"; FAIL=1; }
warn() { printf '%s!%s %s\n' "$YELLOW" "$OFF" "$*"; }

TRACKED="$(git ls-files 2>/dev/null)"

if [ -z "$TRACKED" ]; then
    warn "不是 git 仓库（或没有已跟踪文件），跳过"
    exit 0
fi

# ① 私有数据不该被跟踪
echo "私有数据检查…"
# 精确匹配（用 $ 锚定结尾），别用子串匹配 —— "docs/" 会误伤 "*.doc"
for pattern in 'profile\.yaml$' 'jobs\.db$' '\.docx$' '\.doc$' '/resume/' '/uploads/' '/reports/' '/logs/'; do
    # profile.example.yaml 是该提交的，要排除
    hits="$(printf '%s\n' "$TRACKED" | grep -E "$pattern" | grep -v 'profile\.example\.yaml' || true)"
    if [ -n "$hits" ]; then
        bad "不该被跟踪: $pattern"
        printf '%s\n' "$hits" | sed 's/^/    /'
    fi
done
[ "$FAIL" -eq 0 ] && ok "私有数据检查通过"

# ② 必要的文件都在
echo
echo "必要文件检查…"
for f in README.md LICENSE CHANGELOG.md CONTRIBUTING.md .gitignore .gitattributes \
         src/job_radar/plugin.yaml src/job_radar/dashboard/manifest.json \
         src/job_radar/dashboard/plugin_api.py src/job_radar/desktop/plugin.js \
         src/job_radar/profile.example.yaml docs/ROADMAP.md; do
    if [ -f "$f" ]; then
        ok "$f"
    else
        bad "缺 $f"
    fi
done

# ③ 有没有漏掉 .gitignore 规则
echo
echo ".gitignore 覆盖检查…"
# 用能真正挡住东西的写法来检查，不是照抄字面
while IFS='|' read -r label rule; do
    [ -z "$label" ] && continue
    if grep -qF -- "$rule" .gitignore 2>/dev/null; then
        ok ".gitignore 挡 $label"
    else
        warn ".gitignore 没挡 $label（找 '$rule'）"
    fi
done <<'EOF'
profile.yaml|profile.yaml
jobs.db|jobs.db
__pycache__|__pycache__/
*.pyc|*.py[cod]
reports/|reports/
日志|*.log
EOF

# ④ 桌面端 plugin.js 和仓库版一致？
echo
echo "副本一致性检查…"
if [ -n "${LOCALAPPDATA:-}" ]; then
    RUNTIME="$LOCALAPPDATA/hermes/plugins/job-radar"
else
    RUNTIME="$HOME/.hermes/plugins/job-radar"
fi
if [ -f "$RUNTIME/desktop/plugin.js" ]; then
    if cmp -s "$RUNTIME/desktop/plugin.js" "src/job_radar/desktop/plugin.js"; then
        ok "运行副本与仓库一致"
    else
        warn "运行副本与仓库不一致 —— 跑 scripts/dev.sh sync-desktop"
    fi
else
    warn "找不到运行副本（$RUNTIME）"
fi

echo
if [ "$FAIL" -eq 0 ]; then
    printf '%s✔ 仓库卫生检查通过%s\n' "$GREEN" "$OFF"
    exit 0
else
    printf '%s✘ 仓库卫生检查没过%s\n' "$RED" "$OFF"
    exit 1
fi
