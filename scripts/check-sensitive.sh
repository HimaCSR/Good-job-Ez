#!/usr/bin/env bash
# 发布前脱敏扫描。
#
# 仓库里**不得出现**：真实姓名、手机号、邮箱、本机绝对路径、真实公司名、
# cookie 值、真实简历原文。
#
# 演示数据统一用「张三」「某人力资源有限公司」「user@example.com」。
#
# 用法：bash scripts/check-sensitive.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; DIM=$'\033[2m'; OFF=$'\033[0m'
FAIL=0

# 扫版本控制里的文件 + **未跟踪的新文件**。
# 只扫 git ls-files 会漏掉还没 git add 的新文件 ——
# 正好是新写的文档最容易带隐私路径的时候。
# core.quotepath=false —— 不然 git 会把中文文件名转义成八进制
# （"docs/\346\226\260..."），xargs grep 拿着转义后的名字找不到文件，
# **中文名的文件等于没扫**。
TRACKED="$(git -c core.quotepath=false ls-files --cached --others --exclude-standard 2>/dev/null || \
            find . -type f -not -path './.git/*' -not -name '*.pyc')"

# 有些文件**必须**包含敏感形状（比如测试要验证打码逻辑本身）。
# 在文件首行加 `# sensitive-scan: allow` 就能豁免，但要在豁免清单里登记。
ALLOW_FILES="src/job_radar/tests/test_logging_setup.py"
# 扫描器自己写着这些关键词（否则会自己扫到自己）
SELF="scripts/check-sensitive.sh"

scan() {
    local label="$1" pattern="$2" advice="$3"
    local hits
    hits="$(printf '%s\n' "$TRACKED" | grep -v -F -f <(printf '%s\n' $ALLOW_FILES "$SELF") \
            | xargs grep -InE "$pattern" 2>/dev/null | grep -v '^\./\.git/')"
    if [ -n "$hits" ]; then
        printf '%s✘%s %s\n' "$RED" "$OFF" "$label"
        printf '%s\n' "$hits" | head -12 | sed 's/^/    /'
        printf '  %s→ %s\n\n' "$DIM" "$advice$OFF"
        FAIL=1
    else
        printf '%s✔%s %s\n' "$GREEN" "$OFF" "$label"
    fi
}

# ① 真实姓名（本项目原作者的名字）
scan "真实姓名" "陈智聪" "改成「张三」"

# ② 手机号（中国大陆号段，11 位）
scan "手机号" "(^|[^0-9])1[3-9][0-9]{9}([^0-9]|$)" "删掉或改成示例"

# ③ 真实邮箱（排除 example.com / example.org）
scan "真实邮箱" "[A-Za-z0-9._%+-]+@(?!example\.(com|org))[A-Za-z0-9.-]+\.[A-Za-z]{2,}" \
     "改成 user@example.com"

# ④ 本机绝对路径
#
# 只抓**隐私路径**，不抓系统安装路径 ——
# `C:\Program Files\Git\bin\bash.exe` 所有用户都一样，不是隐私；
# `C:\Users\<你的名字>` 和 `D:\<你自己的盘>` 才是。
scan "本机绝对路径" "C:[/\\]Users[/\\]|/Users/[a-z]|/home/[a-z]|[D-Z]:[/\\]" \
     "改成 <HERMES_HOME> / \$LOCALAPPDATA 之类的占位"

# ⑤ 真实公司名（招聘站抓到的公司）
scan "真实公司名" "杭州东识科技|贵州锦溪人力资源|大连旭诚海圣|杭州云开量智能|杭州未驰网络" \
     "改成「某人力资源有限公司」"

# ⑥ Chrome profile 路径（泄漏本机结构）
scan "Chrome profile 路径" "chrome-hermes-profile" "改成泛化描述"

# ⑦ cookie / token 值（凭证名可以出现，值不行）
scan "cookie 值" "(zp_at|__zp_stoken__|wt2|wbg)[=:]\\s*[A-Za-z0-9_-]{16,}" \
     "凭证值不能进仓库"

# ⑧ 真实简历原文的迹象
scan "简历原文" "本人简历|真实经历原文如下|我叫[\\u4e00-\\u9fff]{2,4}[，,]" \
     "演示数据一律用占位"

echo
if [ -n "$ALLOW_FILES" ]; then
    printf '%s豁免文件（故意包含敏感形状，用于测试打码逻辑）:%s\n' "$DIM" "$OFF"
    printf '    %s\n' $ALLOW_FILES
    printf '  %s新增豁免时要想清楚：这些文件里的值必须是假的%s\n\n' "$DIM" "$OFF"
fi

if [ "$FAIL" -eq 0 ]; then
    printf '%s✔ 脱敏扫描通过%s\n' "$GREEN" "$OFF"
    exit 0
else
    printf '%s✘ 有敏感内容需要清理%s\n' "$RED" "$OFF"
    exit 1
fi
