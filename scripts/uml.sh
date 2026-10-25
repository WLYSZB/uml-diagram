#!/usr/bin/env bash
# ============================================================
#  UML 出图统一入口（v1 · 步骤 2：实现 SKILL_V1_SPEC F1–F5）
#  依赖：Java（任意 11+）、同目录下的 plantuml.jar
#
#  渲染流程（png / svg / pdf / all 统一）：
#    检查输入 → 逐文件 -checkonly → Graphviz -testdot 预检
#    → 隔离渲染到 .workbuddy/staging-* → 确认产物齐全 → 替换正式产物
#
#  环境变量：
#    GRAPHVIZ_DOT          显式 dot 路径：强制使用，预检失败即降级，不再搜索其他位置
#    UML_ALLOW_DEGRADED=1  预检失败时允许产出带降级标记的草稿（仅留临时目录，不替换正式产物）
#    UML_VERBOSE=1         显示 dot 探测过程
#
#  失败策略见 SKILL_V1_SPEC.md（F1–F5）
# ============================================================
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SELF_DIR/.." && pwd)"
JAR="$SELF_DIR/plantuml.jar"
CHECKER="$SELF_DIR/diagram_check.py"
TPL_DIR="$ROOT_DIR/templates"
WB_DIR="$ROOT_DIR/.workbuddy"

# ---- F1：Java 或 jar 缺失，直接失败 ----
if ! command -v java >/dev/null 2>&1; then
  echo "[错误] 找不到 java，请先装 JDK/JRE 并加入 PATH" >&2
  exit 1
fi
if [ ! -f "$JAR" ]; then
  echo "[错误] 缺少引擎：$JAR" >&2
  echo "       重新下载：curl -L -o \"$JAR\" \\" >&2
  echo "       https://maven.aliyun.com/repository/public/net/sourceforge/plantuml/plantuml/1.2025.4/plantuml-1.2025.4.jar" >&2
  exit 1
fi

# 传给 java 的必须是 Windows 风格路径（D:\...），MSYS 的 /d/... 它不认
to_winpath() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1" 2>/dev/null || echo "$1"
  else echo "$1"; fi
}

# ---- dot 定位（F4）：仅当 GRAPHVIZ_DOT 未显式设置时才探测 ----
probe_dot() {
  if command -v dot >/dev/null 2>&1; then command -v dot; return 0; fi
  local c
  for c in \
    "/c/Program Files/Graphviz/bin/dot.exe" \
    "/c/Program Files (x86)/Graphviz/bin/dot.exe" \
    "/d/软件/Graphviz/bin/dot.exe" \
    "/d/Program Files/Graphviz/bin/dot.exe" \
    "/d/Graphviz/bin/dot.exe" \
    "$HOME/AppData/Local/Programs/Graphviz/bin/dot.exe" \
    "$HOME/AppData/Local/Microsoft/WinGet/Packages"Graphviz*/Graphviz*/bin/dot.exe
  do
    [ -x "$c" ] && { echo "$c"; return 0; }
  done
  return 1
}

DOT=""
DOT_EXPLICIT=0
if [ -n "${GRAPHVIZ_DOT:-}" ]; then
  DOT_EXPLICIT=1
  DOT="$(to_winpath "$GRAPHVIZ_DOT")"
  [ -n "${UML_VERBOSE:-}" ] && echo "[布局] GRAPHVIZ_DOT 显式指定：$DOT（不再搜索其他位置）" >&2
else
  if d="$(probe_dot)"; then
    DOT="$(to_winpath "$d")"
    [ -n "${UML_VERBOSE:-}" ] && echo "[布局] 探测到 dot：$DOT" >&2
  else
    [ -n "${UML_VERBOSE:-}" ] && echo "[布局] 未探测到 dot" >&2
  fi
fi

# ---- F4：-testdot 预检。exit 0 且输出含 Installation seems OK 才算通过；
#         [布局] 行只是信息日志，不得当作生效证据 ----
graphviz_ok() {
  if [ -z "$DOT" ]; then
    echo "[降级] 未找到 Graphviz（dot）" >&2
    return 1
  fi
  local out rc
  out="$(java -jar "$JAR" -graphvizdot "$DOT" -testdot 2>&1)"
  rc=$?
  if [ "$rc" -eq 0 ] && printf '%s\n' "$out" | grep -q "Installation seems OK"; then
    echo "[布局] Graphviz: $DOT（-testdot 预检通过）" >&2
    return 0
  fi
  echo "[降级] Graphviz 预检失败：-testdot exit=$rc，路径：$DOT$([ "$DOT_EXPLICIT" -eq 1 ] && echo '（GRAPHVIZ_DOT 显式指定，不再尝试其他位置）')" >&2
  printf '%s\n' "$out" | sed 's/^/       /' >&2
  return 1
}

# ---- 新图种语义校验：只处理带 @diagram 标记的文件，旧文件不引入 Python 依赖 ----
semantic_check() {
  local f="$1"
  if ! grep -Eq "^[[:space:]]*'[[:space:]]*@diagram[[:space:]]" "$f"; then
    return 0
  fi
  if [ ! -f "$CHECKER" ]; then
    echo "[错误] 缺少图种语义校验器：$CHECKER" >&2
    return 1
  fi
  local py="${UML_PYTHON:-python}"
  if ! command -v "$py" >/dev/null 2>&1; then
    echo "[错误] 图种语义校验需要 Python（可用 UML_PYTHON 指定）：$py" >&2
    return 1
  fi
  "$py" "$(to_winpath "$CHECKER")" "$(to_winpath "$f")"
}

# ---- F2：逐文件校验。批量只给笼统错误，必须逐个跑才能定位；-syntax 会挂死，禁用 ----
do_check() {
  local fail=0 f rc log
  for f in "$@"; do
    if [ ! -f "$f" ]; then echo "  [跳过] 文件不存在：$f"; fail=1; continue; fi
    log="$(java -jar "$JAR" -checkonly "$f" 2>&1)"
    rc=$?
    if [ "$rc" -eq 0 ]; then
      if semantic_check "$f"; then
        echo "  [通过] $(basename "$f")"
      else
        echo "  [失败] $(basename "$f")  (语义校验)" >&2
        fail=1
      fi
    else
      echo "  [失败] $(basename "$f")  (exit=$rc)"
      printf '%s\n' "$log" | sed 's/^/         /'
      fail=1
    fi
  done
  return $fail
}

# ---- F3/F4：隔离渲染管线，png / svg / pdf 共用 ----
do_render() {
  local fmt="$1"; shift
  local -a srcs=()
  local -A seen=()
  local f base rc out expected
  for f in "$@"; do
    if [ ! -f "$f" ]; then echo "[错误] 文件不存在：$f" >&2; return 1; fi
    base="$(basename "${f%.*}")"
    if [ -n "${seen[$base]:-}" ]; then
      echo "[错误] 同一次渲染存在同名文件：$base（隔离输出按文件名平铺，会互相覆盖），请分开执行" >&2
      return 2
    fi
    seen[$base]=1
    srcs+=("$f")
  done

  echo "语法校验："
  if ! do_check "${srcs[@]}"; then
    echo "[中止] 校验未通过：不渲染，不产出任何图片。" >&2
    return 1
  fi

  local degraded=0
  if graphviz_ok; then
    :
  elif [ "${UML_ALLOW_DEGRADED:-}" = "1" ]; then
    degraded=1
    echo "[降级] UML_ALLOW_DEGRADED=1：不传 dot，使用 PlantUML 内置布局生成降级草稿。" >&2
  else
    echo "[降级] 未设置 UML_ALLOW_DEGRADED=1：中止，不渲染，不产出任何新 PNG（含临时目录）。" >&2
    return 1
  fi

  # 隔离 staging：项目所在磁盘、.workbuddy/ 下，本次唯一目录；清理只动它自己
  local staging="$WB_DIR/staging-$$-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$staging" || { echo "[错误] 无法创建临时目录：$staging" >&2; return 1; }
  local win_staging
  win_staging="$(to_winpath "$staging")"

  local -a java_args=(-DPLANTUML_LIMIT_SIZE=16384 -jar "$JAR" -o "$win_staging" "-t$fmt")
  if [ $degraded -eq 1 ]; then
    # 不传错误 dot：unset GRAPHVIZ_DOT（PlantUML 会自己读这个环境变量），
    # 并用 -Playout=smetana 强制内置布局，保证草稿确实不经 Graphviz。
    # 注意：不能用 `env -u GRAPHVIZ_DOT java ...`——MSYS 的 env -u 会让 java
    # 静默无输出（退出码 0、不产文件），必须用 bash 内建 unset
    unset GRAPHVIZ_DOT
    java "${java_args[@]}" -Playout=smetana "${srcs[@]}"
  else
    java "${java_args[@]}" -graphvizdot "$DOT" "${srcs[@]}"
  fi
  rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "[错误] 渲染退出码 $rc（认退出码不认文件）。清理本次临时产物，正式产物保持原状。" >&2
    rm -rf "$staging"
    return "$rc"
  fi

  # 认退出码之后，还要确认每个预期产物存在且非空
  for f in "${srcs[@]}"; do
    base="$(basename "${f%.*}")"
    expected="$staging/$base.$fmt"
    if [ ! -s "$expected" ]; then
      echo "[错误] 预期产物缺失或为空：$expected" >&2
      echo "[中止] 产物不齐：清理本次临时产物，正式产物保持原状。" >&2
      rm -rf "$staging"
      return 1
    fi
  done

  # 降级草稿：重命名带标记，只留在 staging，打印路径，不替换正式产物
  if [ $degraded -eq 1 ]; then
    for f in "${srcs[@]}"; do
      base="$(basename "${f%.*}")"
      mv -f "$staging/$base.$fmt" "$staging/${base}-degraded.$fmt"
      echo "[降级] 草稿（内置布局，未使用 Graphviz）：$(to_winpath "$staging")/${base}-degraded.${fmt}"
    done
    echo "[降级] 草稿仅留在上述临时目录，不替换正式产物，不得作为正式交付。" >&2
    return 0
  fi

  # ---- 正式提交：目标预检 → 备份 → 逐文件替换（失败回滚）→ 统一报告 ----
  # 目标预检：任何目标位置已是目录 → 立即整体失败，不执行任何替换
  for f in "${srcs[@]}"; do
    out="${f%.*}.$fmt"
    if [ -d "$out" ]; then
      echo "[错误] 正式产物目标位置已存在同名目录：$out，本次不执行任何替换。" >&2
      rm -rf "$staging"
      return 1
    fi
  done

  # 备份所有既有正式产物到本次 staging/.backup/，并记录哪些目标原本不存在
  local backup_dir="$staging/.backup"
  local -a existed=() absent=()
  mkdir -p "$backup_dir" || { echo "[错误] 无法创建备份目录：$backup_dir" >&2; rm -rf "$staging"; return 1; }
  for f in "${srcs[@]}"; do
    out="${f%.*}.$fmt"
    if [ -e "$out" ]; then
      if ! cp -p "$out" "$backup_dir/"; then
        echo "[错误] 备份既有正式产物失败：$out，本次不执行任何替换。" >&2
        rm -rf "$staging"
        return 1
      fi
      existed+=("$out")
    else
      absent+=("$out")
    fi
  done

  # 逐文件替换；每次替换后确认目标是存在且非空的普通文件，不只依赖 mv 退出码
  local -a gen_msgs=()
  local commit_fail=0
  for f in "${srcs[@]}"; do
    base="$(basename "${f%.*}")"
    out="${f%.*}.$fmt"
    if ! mv -f "$staging/$base.$fmt" "$out"; then
      echo "[错误] 正式产物替换失败：$out" >&2
      commit_fail=1
      break
    fi
    if [ ! -f "$out" ] || [ ! -s "$out" ]; then
      echo "[错误] 替换后目标不是非空普通文件：$out" >&2
      commit_fail=1
      break
    fi
  done

  # 任一替换失败：恢复所有已触碰目标（既有目标从备份还原，原本不存在的只删除本次新建）
  if [ $commit_fail -eq 1 ]; then
    echo "[中止] 正式产物替换失败，开始回滚..." >&2
    local rb_ok=1
    for out in "${existed[@]}"; do
      if ! mv -f "$backup_dir/$(basename "$out")" "$out"; then
        echo "[错误] 回滚失败：$out（备份保留在 $backup_dir）" >&2
        rb_ok=0
      fi
    done
    for out in "${absent[@]}"; do
      if [ -e "$out" ]; then
        if ! rm -f "$out"; then
          echo "[错误] 回滚失败：$out（删除本次新建文件失败）" >&2
          rb_ok=0
        fi
      fi
    done
    if [ $rb_ok -eq 1 ]; then
      rm -rf "$staging"
      echo "[中止] 回滚完成，正式产物保持原状，本次不输出任何 [生成]。" >&2
    else
      echo "[中止] 回滚未完全成功：备份与本次产物保留在 $staging，请人工恢复，勿删除该目录。" >&2
    fi
    return 1
  fi

  # 整批提交全部成功，才统一打印 [生成] 并清理 staging
  for f in "${srcs[@]}"; do
    gen_msgs+=("  [生成] ${f%.*}.$fmt")
  done
  printf '%s\n' "${gen_msgs[@]}"
  rm -rf "$staging"
  return 0
}

usage() {
  cat <<'EOF'
用法：./uml.sh check  a.puml [...]   只校验语法，不出图（不依赖 Graphviz）
      ./uml.sh png    a.puml [...]  出 PNG（300dpi；先校验 → -testdot 预检 → 隔离渲染 → 替换产物）
      ./uml.sh svg    a.puml [...]  出 SVG（同上流程）
      ./uml.sh pdf    a.puml [...]  出 PDF（同上流程）
      ./uml.sh all                  校验并渲染 templates/ 下全部模板
      ./uml.sh clean                删除 templates/ 下生成的图片
环境变量：GRAPHVIZ_DOT（强制 dot 路径）、UML_ALLOW_DEGRADED=1（允许降级草稿）、
          UML_VERBOSE=1（显示 dot 探测过程）
EOF
}

cmd="${1:-help}"
shift 2>/dev/null || true

case "$cmd" in
  check)
    [ $# -eq 0 ] && { echo "用法：./uml.sh check a.puml [...]"; exit 2; }
    echo "语法校验："
    if do_check "$@"; then
      echo "全部通过。"
    else
      echo "存在错误，见上。"
      exit 1
    fi
    ;;
  png|svg|pdf)
    [ $# -eq 0 ] && { echo "用法：./uml.sh $cmd a.puml [...]"; exit 2; }
    do_render "$cmd" "$@" || exit $?
    ;;
  all)
    tpl_files=()
    shopt -s nullglob
    for f in "$TPL_DIR"/[0-9]*.puml; do tpl_files+=("$f"); done
    shopt -u nullglob
    if [ ${#tpl_files[@]} -eq 0 ]; then echo "[错误] $TPL_DIR 下没有模板"; exit 1; fi
    do_render png "${tpl_files[@]}" || exit $?
    ;;
  clean)
    rm -f "$TPL_DIR"/[0-9]*.png "$TPL_DIR"/[0-9]*.svg "$TPL_DIR"/[0-9]*.pdf
    echo "已清理生成的图片。"
    ;;
  *)
    usage
    ;;
esac
