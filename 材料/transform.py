import re

path = r"e:\agent-project\office-agent\材料\项目文档.md"
out_path = r"e:\agent-project\office-agent\材料\项目文档_优化.md"

figtitles = {
    1: "核心功能界面截图组（示意）",
    2: "四大核心创新点协同关系图",
    3: "系统总体架构图",
    4: "典型任务端到端数据流图",
    5: "双次识别智能合并算法流程图",
    6: "三级渐进式文本差异比对算法流程图",
    7: "知识库双模式检索与多租户隔离示意图",
    8: "记忆萃取流水线与四层溯源图结构图",
    9: "纵深防御安全体系图",
}

with open(path, encoding="utf-8") as f:
    src = f.read().split("\n")

out = []
i = 0
while i < len(src):
    line = src[i]
    # remove fenced code blocks (ASCII scaffold superseded by real figures)
    if line.strip() == "```":
        i += 1
        while i < len(src) and src[i].strip() != "```":
            i += 1
        i += 1  # skip closing fence
        continue
    # remove TOC placeholder
    if line.startswith("> **【目录占位】**"):
        i += 1
        continue
    # replace figure placeholder blocks with image + caption
    m = re.match(r"^> \*\*【图 (\d+)｜", line)
    if m:
        n = int(m.group(1))
        while i < len(src) and src[i].startswith(">"):
            i += 1
        title = figtitles.get(n, f"图 {n}")
        # alt-text doubles as the figure caption (pandoc implicit figure)
        out.append(f"![图 {n}　{title}](figures/fig{n}.png){{width=6.0in}}")
        out.append("")
        continue
    out.append(line)
    i += 1

with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(out))

print("done, lines:", len(out))