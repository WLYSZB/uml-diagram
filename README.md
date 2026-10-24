# uml-diagram

UML 图生成与校验 Skill，基于本地 PlantUML + Graphviz，支持七类 UML 图和用例图双档布局。

## 安装

解压 `uml-diagram.zip`，将 `uml-diagram/` 放入 WorkBuddy 用户级 Skill 目录。

## 支持图种

- 类图
- 用例图
- 时序图
- 状态机图
- 活动图
- 组件图
- 部署图

## 主要能力

- 先校验后渲染，失败不交付报错图
- Graphviz `-testdot` 预检，降级行为显式可判定
- 大图使用 `-DPLANTUML_LIMIT_SIZE=16384`，避免静默截断
- 用例图自动版 + 坐标化 precise 版双档输出
- 本地离线运行，不依赖 Docker、Node 或云端渲染

## 目录

```text
uml-diagram/
├── SKILL.md
├── scripts/
├── templates/
├── examples/
└── references/
```

## 版本

- `0.1.0`：首个可安装版本，包含七类模板、校验渲染闭环、用例图坐标化输出和故障处理文档。
