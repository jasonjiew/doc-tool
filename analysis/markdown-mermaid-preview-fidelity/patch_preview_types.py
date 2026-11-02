with open('doc_tool/domain/preview_types.py', 'r', encoding='utf-8') as f:
    content = f.read()

helper_code = '''

def build_block_registry(
    text: str,
    source_file: str = "",
    snapshot_id: str = "",
    prepared_line_map: Optional[Dict[int, Tuple[str, int]]] = None,
) -> BlockRegistry:
    """从 Markdown 源码或准备结果构建结构化块注册表（REQ-MD-04、REQ-MD-06）。
    
    能够准确映射重复标题、多段相同代码/图表及展开模块来源行。
    """
    import re
    registry = BlockRegistry(snapshot_id=snapshot_id, source_file=source_file)
    lines = (text or "").splitlines()
    total = len(lines)
    i = 0

    while i < total:
        line = lines[i]
        line_no = i + 1
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # 1. 标题
        if stripped.startswith("#"):
            m = re.match(r"^(#{1,6})\s+(.*?)\s*$", stripped)
            if m:
                title = m.group(2)
                real_file = source_file
                real_line = line_no
                metadata = {}
                if prepared_line_map and line_no in prepared_line_map:
                    real_file, real_line = prepared_line_map[line_no]
                    metadata["mapped_from"] = f"{source_file}:{line_no}"
                registry.add_block(BlockLocation(
                    block_id=f"line-{line_no}",
                    source_file=real_file,
                    start_line=real_line,
                    end_line=real_line,
                    kind="heading",
                    title=title,
                    metadata=metadata,
                ))
                i += 1
                continue

        # 2. 围栏代码块 / Mermaid
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence = stripped[:3]
            info = stripped[3:].strip()
            start_l = line_no
            end_l = line_no
            code_lines = []
            i += 1
            while i < total:
                cur = lines[i]
                if cur.strip().startswith(fence):
                    end_l = i + 1
                    i += 1
                    break
                code_lines.append(cur)
                end_l = i + 1
                i += 1
            kind = "mermaid" if info.lower() == "mermaid" else "code"
            real_file = source_file
            real_start = start_l
            real_end = end_l
            metadata = {"info": info, "code": "\\n".join(code_lines)}
            if prepared_line_map and start_l in prepared_line_map:
                real_file, real_start = prepared_line_map[start_l]
                if end_l in prepared_line_map:
                    _, real_end = prepared_line_map[end_l]
                else:
                    real_end = real_start + (end_l - start_l)
            registry.add_block(BlockLocation(
                block_id=f"line-{start_l}",
                source_file=real_file,
                start_line=real_start,
                end_line=real_end,
                kind=kind,
                metadata=metadata,
            ))
            continue

        # 3. 提示块
        if stripped.startswith(">"):
            start_l = line_no
            end_l = line_no
            is_callout = bool(re.search(r">\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]", stripped, re.I))
            i += 1
            while i < total and lines[i].strip().startswith(">"):
                end_l = i + 1
                i += 1
            real_file = source_file
            real_start = start_l
            real_end = end_l
            metadata = {}
            if prepared_line_map and start_l in prepared_line_map:
                real_file, real_start = prepared_line_map[start_l]
                if end_l in prepared_line_map:
                    _, real_end = prepared_line_map[end_l]
                else:
                    real_end = real_start + (end_l - start_l)
            registry.add_block(BlockLocation(
                block_id=f"line-{start_l}",
                source_file=real_file,
                start_line=real_start,
                end_line=real_end,
                kind="callout" if is_callout else "quote",
                metadata=metadata,
            ))
            continue

        # 4. 表格
        if stripped.startswith("|") and stripped.endswith("|"):
            start_l = line_no
            end_l = line_no
            i += 1
            while i < total and lines[i].strip().startswith("|"):
                end_l = i + 1
                i += 1
            real_file = source_file
            real_start = start_l
            real_end = end_l
            if prepared_line_map and start_l in prepared_line_map:
                real_file, real_start = prepared_line_map[start_l]
                if end_l in prepared_line_map:
                    _, real_end = prepared_line_map[end_l]
                else:
                    real_end = real_start + (end_l - start_l)
            registry.add_block(BlockLocation(
                block_id=f"line-{start_l}",
                source_file=real_file,
                start_line=real_start,
                end_line=real_end,
                kind="table",
            ))
            continue

        # 5. 普通段落或列表
        start_l = line_no
        end_l = line_no
        is_list = bool(re.match(r"^(\*|-|\+|\d+\.)\s+", stripped))
        i += 1
        while i < total and lines[i].strip() and not lines[i].strip().startswith(("#", "```", "~~~", ">", "|")):
            end_l = i + 1
            i += 1
        real_file = source_file
        real_start = start_l
        real_end = end_l
        if prepared_line_map and start_l in prepared_line_map:
            real_file, real_start = prepared_line_map[start_l]
            if end_l in prepared_line_map:
                _, real_end = prepared_line_map[end_l]
            else:
                real_end = real_start + (end_l - start_l)
        registry.add_block(BlockLocation(
            block_id=f"line-{start_l}",
            source_file=real_file,
            start_line=real_start,
            end_line=real_end,
            kind="list" if is_list else "paragraph",
        ))

    return registry
'''

if 'def build_block_registry' not in content:
    content += helper_code
    with open('doc_tool/domain/preview_types.py', 'w', encoding='utf-8', newline='') as f:
        f.write(content)
    print("Added build_block_registry to preview_types.py")
else:
    print("build_block_registry already present")
