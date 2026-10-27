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
         src/job_radar/dashboard/plugin_api.py src/desktop/job-radar/plugin.js \
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

# ④ 运行副本和仓库版一致？
#
# 只查 desktop/plugin.js 是不够的 —— 之前就漏过 logging_setup.py，
# 仓库里少了 shutdown 时要用的 stream 属性补丁，退出时才炸。
# 这里逐个文件比。
echo
echo "副本一致性检查…"
if [ -n "${LOCALAPPDATA:-}" ]; then
    RUNTIME="$LOCALAPPDATA/hermes/plugins/job-radar"
else
    RUNTIME="$HOME/.hermes/plugins/job-radar"
fi
if [ -d "$RUNTIME" ]; then
    # junction 模式：运行目录**就是**仓库 src/job_radar（同一份文件），
    # 没有副本可对 —— 比对会永远是「一致」，纯噪音。
    if [ -z "$(readlink "$RUNTIME" 2>/dev/null)" ] && \
       ! grep -q . /dev/null; then :; fi
    LINKTYPE="$(powershell -NoProfile -Command \
        "(Get-Item '$RUNTIME').LinkType" 2>/dev/null | tr -d '\r')"
    if [ "$LINKTYPE" = "Junction" ]; then
        ok "运行目录是 junction → 仓库即运行副本（无需同步）"
        RUNTIME=""
    fi
fi

if [ -n "$RUNTIME" ] && [ -d "$RUNTIME" ]; then
    DRIFT=0
    CHECKED=0
    while IFS= read -r rel; do
        [ -z "$rel" ] && continue
        CHECKED=$((CHECKED + 1))
        if ! cmp -s "$RUNTIME/$rel" "src/job_radar/$rel"; then
            bad "运行副本与仓库不一致: $rel"
            printf '      → 跑 scripts/dev.sh sync\n'
            DRIFT=1
        fi
    done < <(cd "$RUNTIME" && find . -type f \( -name '*.py' -o -name '*.js' -o \
                -name '*.yaml' -o -name '*.json' \) \
                -not -path './__pycache__/*' -not -path './tests/__pycache__/*' \
                | sed 's|^\./||' | sort)
    [ "$DRIFT" -eq 0 ] && ok "运行副本与仓库一致（$CHECKED 个文件）"
elif [ -n "$RUNTIME" ]; then
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
