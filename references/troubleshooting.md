# 故障处理（已验证的处置，全部来自实测）

## 1. 语法校验

- 一律用 `java -jar plantuml.jar -checkonly 文件`；**禁用 `-syntax`**——它会等待 GUI 事件循环挂死（headless 也救不了，实测 timeout 10s 被强杀）。
- **逐文件校验，不要批量**：批量多文件时只要有一个错就返回 200，但不告诉你是哪个文件。
- 退出码 200 = 有语法错误；0 = 通过。校验失败时渲染命令必须中止，不得出图。
- 渲染含语法错误的文件：退出码 200，但仍会写出一张"错误提示图"。**认退出码，不认文件是否存在**——这就是为什么 uml.sh 先校验后渲染、隔离渲染。

## 2. Graphviz 预检与降级

- 找不到 dot 或路径写错时，PlantUML **静默降级**：退出码 0、无输出、图照出（降级布局）。不能靠退出码判断布局引擎是否生效。
- 正确做法：渲染前用同一 jar、同一 `-graphvizdot` 路径执行 `-testdot`。实测：有效 dot → exit 0 且输出 `Installation seems OK. File generation OK`；无效路径 → exit 127 且输出 `Dot executable does not exist`。
- `GRAPHVIZ_DOT` 环境变量一旦显式设置就是强制路径：预检失败直接进入降级流程，**不得自动改用其他 dot 冒充**。
- 降级策略：默认打印 `[降级]` 并以非 0 退出，不渲染、不产图；只有显式设置 `UML_ALLOW_DEGRADED=1` 才产出带"降级"标记的草稿（内部改用 Smetana 布局，不传 dot），草稿不替换正式产物、不算交付成功。
- 本机当前 MSYS 环境实测：`env -u GRAPHVIZ_DOT java ...` 会让 java 渲染静默无输出（退出码 0、不产文件）。用 bash 内建 `unset`；其他 Git Bash 环境若要用 `env -u`，先自行验证。

## 3. 超大图截断

- PlantUML 默认把输出限制在 **4096×4096**，超出部分**静默截断**：不报错、退出码 0，只是图缺一块。
- 渲染命令必须带 `-DPLANTUML_LIMIT_SIZE=16384`（JVM 参数放在 `-jar` 之前）。uml.sh 已内置。
- 实测案例：ATM 完整时序图 3456×7105，不带该参数高度被截到 4096。

## 4. 隔离渲染与提交回滚

- 正式渲染一律先写独立临时目录，全部文件渲染成功且产物齐全（存在、非空）后才替换正式产物；任一失败只清理临时目录，正式产物保持原状。
- 旧图不当作本次成功产物，也不要求删除；失败时不得交付旧图冒充新图。
- 多文件替换必须整批提交：先备份既有产物，任一替换失败即回滚全部已触碰目标（原本不存在的按新建文件删除）。
- 目标位置已有同名**目录**时（如存在 `foo.png/` 目录）必须整体失败，不得把文件塞进目录里谎报成功。

## 5. SVG 字体与 PNG 交付

- SVG 里的字体只有"引用"没有"嵌入"（`font-face` 出现 0 次）：theme.puml 指定微软雅黑时写 `font-family="Microsoft YaHei"`，不指定则写 `sans-serif` 交给对方系统猜，换机可能走形。
- **正式交付一律 PNG**；SVG 只作可编辑中间产物，不外发。
- theme.puml 已固定 `skinparam dpi 300` + 微软雅黑；不要单独调 dpi（默认实际是 95.6dpi，屏幕上看不出、打印才暴露）。
- SVG 交付前必须通过 XML 解析验证；PNG 交付前核对 IHDR 尺寸。

## 6. Edge 无头截图（用例图 precise PNG）

- SVG→PNG 无第三方转换器（本机无 magick/inkscape/rsvg/Pillow），用系统自带 Edge。
- 路径解析：`UML_EDGE` 显式指定即强制，无效直接失败不换浏览器；未指定时探测 `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe` 及 64 位路径。
- 已验证参数：`--headless --disable-gpu --disable-extensions --hide-scrollbars --force-device-scale-factor=1 --no-first-run --window-size=<宽>,<高> --screenshot=<绝对路径> --user-data-dir=<独立临时目录> <SVG 的 file URI>`。
- **user-data-dir 必须是本次独立临时目录**，绝不能指向用户日常 Edge 配置。
- stderr 出现 `QQBrowser user data path not found` 等日志无害，**不能仅凭 stderr 非空判失败**。
- 成功判据：exit 0 + PNG 存在非空 + PNG 文件头合法 + IHDR 尺寸 == SVG viewBox。
- file URI 用 `Path.as_uri()` 生成，自动处理中文和空格路径。

## 7. jar 下载

- 缺 jar 时优先阿里云 Maven 镜像，GitHub 作备选——**理由是镜像快 6–9 倍**（实测镜像 2.0s vs GitHub 11.5–18.1s），不是 GitHub 下不了（GitHub 实测可完整下载 22.6MB，早年"必然断流"的结论已被推翻）。
- 阿里云：`https://maven.aliyun.com/repository/public/net/sourceforge/plantuml/plantuml/1.2025.4/plantuml-1.2025.4.jar`
- 备选：`https://github.com/plantuml/plantuml/releases/download/v1.2025.4/plantuml-1.2025.4.jar`
- 完整性核对：22,592,450 字节。

## 8. 图种语义校验（v0.2）

- 只对文件内带 `' @diagram <类型>` 标记的文件生效；无标记的旧文件只做语法校验，不引入 Python 依赖。
- 校验器是 `scripts/diagram_check.py`（Python 3 标准库），由 `uml.sh check/png` 在 PlantUML 语法校验通过后自动调用；`UML_PYTHON` 可指定解释器。
- 失败输出格式：`[错误] 文件:行号: 原因：原文`，最后 `[失败] <文件名> 语义校验未通过（N 处错误）`；退出码非 0，**不进入渲染、不产出任何新图**，旧产物保持原状。
- 常见错误与修法：
  - `数据流必须填写标签`：给箭头补 `: 流名`；标签是数据的名字，不是动作描述。
  - `孤立 DFD 节点` / `数据流端点未定义`：声明的节点必须参与至少一条流；别名拼写要一致。
  - `外部实体不能直接连接外部实体` / `数据存储不能直接连接数据存储`：数据必须经过处理过程中转。
  - `子图缺少父上下文图的外部数据流` / `子图新增外部数据流`：0 层图与上下文图的外部接口必须逐条平衡（外部实体别名、方向、标签三元组完全一致）。
  - `DFD 父文件循环引用` / `父图类型应为 …`：`@parent` 只能指向上一层（level0 → context，level1 → level0），不得成环。
  - `流程图必须恰有一个 start`（stop 为"至少一个"，多出口合法）、`if 判断必须有 then 分支标签`、`while 循环必须有 is 分支标签`：按错误行号补齐；标签压短，完整条件写进 note。
  - `switch 不支持 else/default 兜底分支`：本机 PlantUML 1.2025.4 实测 `else`/`default` 在 switch 内是语法错误（rc=200），PlantUML 层即拦截；带标记文件同时被校验器显式拦截并给指路——剩余情况写显式 case（如 `case (g < 60 ?)`），或改用 `if/elseif`。
  - `case 分支必须有标签` / `case 只能出现在 switch 块内` / `endswitch 没有对应 switch`：补标签、把 case 归位到 switch 块内或补 endswitch。
  - `异常分支必须包含处理动作`：失败分支（else/elseif/case）不能只有判断没有出路，补处理动作和出口。
- 校验器对无法识别的已标记图种报 `未注册的图种类型`（清单在 `diagram-types.json`），不会静默跳过。
