import mistune
import yaml
import re
import fitz     # 新增 PyMuPDF
from pathlib import Path
from LaTeXRenderer import LaTeXRender
from mistune.plugins.math import math
from mistune.plugins.table import table

# =====================================================================
# 基础配置区：在此处设置输入/输出路径，以及是否输出完整的 tex 文件
# =====================================================================
INPUT_MD_FILE = r"Chapters/02_数列极限.md"
OUTPUT_TEX_FILE = r"Chapters/02_数列极限.tex"
OBSIDIAN_IMAGE_DIR = r"Chapters/images"
OBSIDIAN_PDF_DIR = r"books"
default_convert_config_path = "default_convert_config.yaml"


def fix_latex_env_nesting_with_stack(latex_str):
    """
    使用栈结构，彻底解决 Markdown 渲染后 LaTeX 嵌套环境闭合错位的问题。
    """
    import re
    # 拆分文档为 [text, tag, text, tag...]
    pattern = re.compile(r'(\\(?:begin|end)\{[a-zA-Z0-9_*-]+\})')
    parts = pattern.split(latex_str)

    stack = []
    i = 1
    while i < len(parts):
        tag = parts[i]

        if tag.startswith(r'\begin'):
            env = re.search(r'\\begin\{([^\}]+)\}', tag).group(1)
            stack.append(env)
            i += 2

        elif tag.startswith(r'\end'):
            # 找到一个 end，开始向后探索“闭合簇”
            cluster_indices = [i]
            envs_in_cluster = [re.search(r'\\end\{([^\}]+)\}', tag).group(1)]

            j = i + 2
            while j < len(parts):
                text_between = parts[j - 1]
                # 核心：允许闭合标签之间有空白、换行和 Mistune 残留的 "}"
                if not re.match(r'^[\s\}]*$', text_between):
                    break
                next_tag = parts[j]
                if next_tag.startswith(r'\end'):
                    cluster_indices.append(j)
                    envs_in_cluster.append(re.search(r'\\end\{([^\}]+)\}', next_tag).group(1))
                    j += 2
                else:
                    break

            # 确定环境在栈中的优先级（从右往左找，越靠近栈顶，越早闭合）
            def get_stack_priority(e):
                for k in range(len(stack) - 1, -1, -1):
                    if stack[k] == e:
                        return -k  # 加负号，使得栈顶(索引大)排在最前面
                return 0

            # 按照栈的优先级，对这批 \end 标签重新排序！
            sorted_envs = sorted(envs_in_cluster, key=get_stack_priority)

            # 回填重排后的正确标签
            for idx, env in zip(cluster_indices, sorted_envs):
                parts[idx] = f"\\end{{{env}}}"

            # 从栈中移除这些已闭合的环境
            for env in sorted_envs:
                for k in range(len(stack) - 1, -1, -1):
                    if stack[k] == env:
                        stack.pop(k)
                        break
            i = j
        else:
            i += 2

    return "".join(parts)


def normalize_display_math(text):
    """
    规范化 $$ 写法，同时【严格保留】公式所在行的前导缩进空格。
    这是保证公式不脱离 List（列表项）的核心！
    """
    lines = text.split('\n')
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 【关键修复】：提取该行前面的空格（缩进）
        indent = line[:len(line) - len(stripped)]

        if stripped.startswith('$$') and stripped != '$$':
            rest = stripped[2:]
            if rest.endswith('$$') and len(rest) > 2:
                inner = rest[:-2].rstrip()
                result.append(indent + '$$')  # 带着缩进输出
                result.append(indent + inner)
                result.append(indent + '$$')
                i += 1
                continue

            block_lines = [rest]
            i += 1
            while i < len(lines):
                l = lines[i]
                ls = l.strip()
                if ls == '$$':
                    result.append(indent + '$$')
                    result.extend([indent + bl.strip() for bl in block_lines])
                    result.append(indent + '$$')
                    i += 1
                    break
                elif ls.endswith('$$') and ls != '$$':
                    block_lines.append(ls[:-2].rstrip())
                    result.append(indent + '$$')
                    result.extend([indent + bl.strip() for bl in block_lines])
                    result.append(indent + '$$')
                    i += 1
                    break
                else:
                    block_lines.append(l)
                    i += 1
            continue

        elif stripped == '$$':
            result.append(indent + '$$')
            i += 1
            while i < len(lines):
                l = lines[i]
                ls = l.strip()
                if ls == '$$':
                    result.append(indent + '$$')
                    i += 1
                    break
                elif ls.endswith('$$') and ls != '$$':
                    result.append(ls[:-2].rstrip())  # 保持相对缩进
                    result.append(indent + '$$')
                    i += 1
                    break
                else:
                    result.append(l)  # 保持内部多行公式自带的排版缩进
                    i += 1
            continue

        result.append(line)
        i += 1

    return '\n'.join(result)



def process_obsidian_callouts(text):

    lines = text.split('\n')
    result = []
    in_callout = False
    callout_type = ""
    callout_indent = ""

    for line in lines:
        if not in_callout:
            # 寻找 Callout 起始标志：允许前置缩进，匹配 > [!type] title
            match = re.match(r'^([ \t]*)(?:>[ \t]*)\[!([a-zA-Z0-9_-]+)\](.*)', line)
            if match:
                in_callout = True
                callout_indent = match.group(1)
                callout_type = match.group(2).strip()
                title = match.group(3).strip()

                # 【核心修复1】：在 \begin 之前和之后强加空行，防止和上下文段落粘连
                result.append("")
                if title:
                    result.append(f"{callout_indent}\\begin{{{callout_type}}}[{title}]")
                else:
                    result.append(f"{callout_indent}\\begin{{{callout_type}}}")
                result.append("")
            else:
                result.append(line)
        else:
            # 在 Callout 内部：只要当前行带着 > （以及相应的缩进），就是同一块
            match_cont = re.match(r'^([ \t]*)(?:>[ \t]?)(.*)', line)
            if match_cont:
                # 剥离了 `> `，但保留原始缩进
                indent = match_cont.group(1)
                content = match_cont.group(2)
                result.append(f"{indent}{content}")
            else:
                # 遇到不带 > 的行，或者真正的空行，说明 Callout 结束
                # 【核心修复2】：在 \end 之前强加空行，绝对禁止它被吸入上一行的 \item 里面！！！
                result.append("")
                result.append(f"{callout_indent}\\end{{{callout_type}}}")
                result.append("")
                in_callout = False
                result.append(line)

    # 兜底：如果文章末尾还在 Callout 里，及时闭合
    if in_callout:
        result.append("")
        result.append(f"{callout_indent}\\end{{{callout_type}}}")
        result.append("")

    return '\n'.join(result)

def preprocess_markdown(text, output_dir):
    text = process_obsidian_callouts(text)
    # 1. 把前面粘连的文字推开（保留空行，切断与正文的联系）
    text = re.sub(r'([^\s])[ \t]*\$\$', r'\1\n\n$$', text)

    # 2. 把后面紧跟的公式推到下一行（只能用 \n 单换行！绝对不能有空行！）
    text = re.sub(r'\$\$[ \t]*([^\s\n])', r'$$\n\1', text)
    # =================================================================
    def split_math_start(m):
        indent = m.group(1)
        content = m.group(2)
        # 如果紧跟在列表（数字或 -*+）之后，强制给 $$ 续上 4 个空格缩进，避免列表断裂
        pad = "    " if re.match(r'^(\d+\.|[-*+])\s', content.lstrip()) else ""
        return f"{indent}{content}\n{indent}{pad}$$"

    # 1. 拆开前面的文字：把 "文字$$" 变成 "文字\n$$"，并智能继承缩进
    text = re.sub(r'^([ \t]*)(.+?[^\s])\s*\$\$', split_math_start, text, flags=re.MULTILINE)

    # 2. 拆开后面的环境：把 "$$\begin" 变成 "$$\n\begin"，只加单换行，公式环境绝不断裂！
    text = re.sub(r'^([ \t]*)\$\$\s*([^\s][^\n]*)', r'\1$$\n\1\2', text, flags=re.MULTILINE)

    # =================================================================
    # =================================================================
    def process_pdf_extract(match):
        pdf_name = match.group(1).strip()
        page_num = int(match.group(2))
        rect_str = match.group(3)
        caption = match.group(4) if match.group(4) else "PDF Image"

        # 1. 寻找 PDF 源文件
        pdf_path = Path(OBSIDIAN_PDF_DIR ) / pdf_name
        if not pdf_path.exists():
            print(f"警告：找不到 PDF 文件 {pdf_path}")
            # 【修改】返回显眼的警告文本，防止 LaTeX 编译因为找不到图片而崩溃
            return f"\n**[⚠️ 图片截取失败：在目录中找不到文件 `{pdf_name}`]**\n"

        # 2. 准备输出文件夹 (严格与生成的tex文件同级)
        img_dir = output_dir.parent / "images"
        img_dir.mkdir(parents=True, exist_ok=True)

        # 3. 命名
        book_name = Path(pdf_name).stem.replace(' ', '_')
        safe_rect_str = rect_str.replace(',', '_')
        img_filename = f"{book_name}_{page_num}_{safe_rect_str}.pdf"
        img_path = img_dir / img_filename

        # 4. 提取为裁剪后的局部 PDF 文件
        try:
            doc = fitz.open(str(pdf_path))
            doc2 = fitz.open()
            doc2.insert_pdf(doc, from_page=page_num - 1, to_page=page_num - 1)
            page2 = doc2[0]

            coords = [float(x) for x in rect_str.split(',')]
            x_left, y_bottom, x_right, y_top = coords

            page_height = page2.rect.height
            clip_rect = fitz.Rect(x_left, page_height - y_top, x_right, page_height - y_bottom)

            page2.set_cropbox(clip_rect)
            doc2.save(str(img_path))
            doc2.close()
            doc.close()
            print(f"成功提取矢量图片：{img_filename}")
        except Exception as e:
            print(f"提取 PDF {pdf_name} 失败: {e}")
            # 【修改】报错时同样返回安全文本
            return f"\n**[⚠️ 图片截取失败：解析 `{pdf_name}` 出错，请检查坐标范围]**\n"

        # 5. 返回标准 Markdown 图片格式，使用相对路径指向同级的 images
        return f"![{caption}](images/{img_filename})"

    # 1. 处理 PDF 裁剪图片 (保持原样)
    pdf_pattern = r'!\[\[([^\]]+\.pdf)#page=(\d+)&rect=([\d.,]+)[^|\]]*(?:\|([^\]]+))?\]\]'
    text = re.sub(pdf_pattern, process_pdf_extract, text)

    # 2. 【核心修复】：处理普通图片双链，并【物理拷贝】文件到父级 images 目录
    def convert_and_copy_images(match):
        import shutil
        inner = match.group(1).strip()
        # 处理带备注的情况 ![[xxx.jpg|备注]]
        if '|' in inner:
            filename, caption = inner.split('|', 1)
        else:
            filename, caption = inner, ""

        filename = filename.strip()

        # 源文件路径：假设在 .md 文件的同级目录
        source_path = Path(OBSIDIAN_IMAGE_DIR ) / filename

        # 目标目录路径：.tex 所在目录的上一级 (parent) 下的 images 文件夹
        # 注意：这里的 output_dir 必须在 convert 函数中已经定义（即 output_path.parent）
        target_dir = Path("images")
        target_dir.mkdir(parents=True, exist_ok=True)

        # 目标文件绝对路径
        target_path = target_dir / filename

        if source_path.exists():
            # 执行物理拷贝
            shutil.copy(source_path, target_path)
            print(f"成功物理搬运手动图片至父级目录: {filename}")
        else:
            # 调试信息：如果找不到，打印出它尝试寻找的具体路径
            print(f"警告：找不到图片原文件，请检查路径: {source_path.absolute()}")

        # ==================== 👇 修改这里 👇 ====================
        # 返回前把空格替换为占位符，防止 Mistune 断行
        safe_filename = filename.replace(" ", "@@@SPACE@@@")
        return f"![{caption}]({safe_filename})"
        # ==================== 👆 修改这里 👆 ====================


    # 简化版正则，匹配 ![[内容]] 且内容包含图片后缀
    text = re.sub(r'!\[\[([^\]]*?\.(?:jpg|jpeg|png|pdf|svg|webp)[^\]]*?)\]\]', convert_and_copy_images, text)

    # ==================== 👇 新增这里 👇 ====================
    # 2. 同时处理标准 Markdown 图片格式 ![alt](url)
    def convert_standard_image_links(match):
        caption = match.group(1).strip()
        path_str = match.group(2).strip()
        # 保护路径中的空格
        safe_path = path_str.replace(" ", "@@@SPACE@@@")
        return f"![{caption}]({safe_path})"

    # 匹配 ![caption](path)
    text = re.sub(r'!\[(.*?)\]\((.*?)\)', convert_standard_image_links, text)
    # ==================== 👆 新增这里 👆 ====================
    # 3. 删除剩下的非图片普通双链（如 [[纯文本链接]]）
    text = re.sub(r'\[\[.*?\]\]', '', text)
    # 保护手写的 equation
    protected_eqs = {}

    def mask(m):
        key = f"__EQ_{len(protected_eqs)}__"
        protected_eqs[key] = m.group(0)
        return key

    text = re.sub(r'\\begin\{equation\}.*?\\end\{equation\}', mask, text, flags=re.DOTALL)

    # 执行 $$ 规范化
    text = normalize_display_math(text)

    # 还原
    for key, val in protected_eqs.items():
        text = text.replace(key, val)
        # =================================================================
        # 【追加修复】：强制给所有 # 标题前加绝对空行，防止 Mistune 将其识别为普通正文
        # =================================================================
    text = re.sub(r'([^\n])\n([ \t]*#{1,6}\s)', r'\1\n\n\2', text)
    return text


def convert(md_path, customer_convert_config_path, output_path):
    md_path = Path(md_path)
    customer_convert_config_path = Path(customer_convert_config_path)
    output_path = Path(output_path)

    # 确保拿到最终 tex 文件的所在目录
    output_dir = output_path.parent

    with open(md_path, 'r', encoding='utf-8') as f:
        markdown_text = f.read()
        # 传入 output_dir 给预处理函数，保证图片存放到正确位置
        markdown_text = preprocess_markdown(markdown_text, output_dir)

    with open(default_convert_config_path, 'r') as f:
        default_convert_config = yaml.load(f, Loader=yaml.FullLoader)

    if customer_convert_config_path.exists():
        with open(customer_convert_config_path, 'r') as f:
            customer_convert_config = yaml.load(f, Loader=yaml.FullLoader)
        config = {**default_convert_config, **customer_convert_config}
    else:
        config = default_convert_config
    raw_texts = {}

    def protect_raw_text(match):
        key = f"SAFETEXT{len(raw_texts)}K"
        raw_texts[key] = match.group(1)
        return key

    markdown_text = re.sub(r'(?:<|&lt;)text(?:>|&gt;)(.*?)(?:</|&lt;/)text(?:>|&gt;)', protect_raw_text, markdown_text,
                           flags=re.DOTALL | re.IGNORECASE)

    # 【核心修复1】：精准捕捉 $$ 后面的空行！
    # 如果你在 Markdown 里敲了空行（两个 \n），我们就在这里强行塞入一个路标。
    # 这样 Mistune 解析时就会被迫把它分成两个段落。
    # =================================================================
    markdown_text = re.sub(r'(?:<|&lt;)text(?:>|&gt;)(.*?)(?:</|&lt;/)text(?:>|&gt;)', protect_raw_text, markdown_text,
                           flags=re.DOTALL | re.IGNORECASE)

    # =================================================================
    # 【第一步：占位符替换】在传给 Mistune 之前，把所有的 \\ 和 & 藏起来
    # =================================================================
    markdown_text = markdown_text.replace(r'\\', '@@@BR@@@') \
        .replace('&', '@@@AMP@@@') \
        .replace('_', '@@@SUB@@@')  # 新增：处理下标符号    # =================================================================

    # 【核心修复1】：精准捕捉 $$ 后面的空行！
    markdown_text = re.sub(r'\$\$([ \t]*\n[ \t]*\n)', r'$$\nSAFEPARABREAK\n\n', markdown_text)
    render = LaTeXRender(my_config=config)

    # 删掉 math_in_list，只保留 math
    markdown = mistune.create_markdown(renderer=render, plugins=[math, table])

    # Mistune 解析，此时它不认识占位符，会原样保留
    latex = markdown(markdown_text)

    # =================================================================
    # 【第二步：原样还原】在渲染完后，立刻变回来
    # =================================================================
    latex = latex.replace('@@@BR@@@', r'\\') \
        .replace('@@@AMP@@@', '&') \
        .replace('@@@SUB@@@', '_') \
        .replace('@@@SPACE@@@', ' ')

    # 【终极修复】：强行给所有 \includegraphics 的大括号路径套上双引号！

    latex = re.sub(r'\\includegraphics(\[.*?\])?\{([^}"]+)\}', r'\\includegraphics\1{"\2"}', latex)
    # ==================== 👇 1. 新增：调用基于栈的闭合修复函数 👇 ====================
    latex = fix_latex_env_nesting_with_stack(latex)

    # 【追加修复】：将错位的 } 和 \end{enumerate} 移出 $$ 公式环境
    # =================================================================
    latex = re.sub(r'\}\s*(\\end\{(?:enumerate|itemize)\})\s*\$\$', r'\n$$\n}\n\1\n', latex)
    # =================================================================

    # 1. 修复 \end{aligned}\tag{x} 结构
    latex = re.sub(r'\\end\{aligned\}\s*\\tag\{([\d\.]+)\}', r'\\end{aligned}\n\\tag{\1}', latex)

    # 2. 修复行尾直接出现 \tag 的情况
    latex = re.sub(r'([^\s])(\\tag\{[\d\.]+\})', r'\1 \2', latex)

    # 3. 终极修复：确保所有 \tag{x} 都在 $$ 闭合前，而不是在 aligned 内
    latex = re.sub(r'(\\begin\{aligned\}.*?)(\\tag\{[\d\.]+\})\s*(\\end\{aligned\})',
                   r'\1\3 \2', latex, flags=re.DOTALL)

    # # --------------------------------------------------------
    # latex = re.sub(r'\{(?:\\rootpath/|\.\./)([^}]+)\}', r'{images/\1}', latex)

    # 修复浮动体后非法换行：删除 \end{figure} 后面的空白符（包括 Tab）和强制换行符 \\
    latex = re.sub(r'\\end\{figure\}\s*\\\\', r'\\end{figure}\n', latex)

    # 修复 Underfull \hbox：清理段落末尾用于换行的独立 \\，恢复为标准的 LaTeX 双回车分段
    latex = re.sub(r'\\\\\s*\n\s*\n', r'\n\n', latex)

    # 修复 \begin{equation} 内部的空行（LaTeX 不允许数学环境内有空段落）
    latex = re.sub(
        r'(\\begin\{equation\})(.*?)(\\end\{equation\})',
        lambda m: m.group(1) + re.sub(r'\n\s*\n', '\n', m.group(2)) + m.group(3),
        latex,
        flags=re.DOTALL
    )

    # -------- 终极洗地：修复公式环境的双重嵌套 --------
    # 清除 \begin{equation} 外层的 $$
    latex = re.sub(r'\$\$\s*\\begin\{equation\}', r'\\begin{equation}', latex)
    # 清除 \end{equation} 外层的 $$
    latex = re.sub(r'\\end\{equation\}\s*\$\$', r'\\end{equation}', latex)
    # --------------------------------------------------

    # 修复可能由模板错误导致的表格三线表被错误转义为 \\midrule 的情况
    latex = latex.replace(r'\\toprule', r'\toprule')
    latex = latex.replace(r'\\midrule', r'\midrule')
    latex = latex.replace(r'\\bottomrule', r'\bottomrule')
    latex = re.sub(r'\\\\(\s*)\\midrule', r'\\\\\n\\midrule', latex)

    # =================================================================
    # 新增：处理 HTML 颜色标签和下划线标签 (终极防弹版)
    # =================================================================

    # 1. 处理 HEX 颜色标签: <font color="#c00000">内容</font>
    # 兼容 &lt;font...&gt; 以及大小写
    latex = re.sub(
        r'(?:<|&lt;)font\s+color="?\\?#([0-9A-Fa-f]{6})"?.*?([>|&gt;])(.*?)(?:</|&lt;/)font(?:>|&gt;)',
        r'\\textcolor[HTML]{\1}{\3}',
        latex,
        flags=re.DOTALL | re.IGNORECASE
    )

    # 2. 处理纯文本颜色标签: <font color="red">内容</font>
    latex = re.sub(
        r'(?:<|&lt;)font\s+color="?([a-zA-Z]+)"?.*?([>|&gt;])(.*?)(?:</|&lt;/)font(?:>|&gt;)',
        r'\\textcolor{\1}{\3}',
        latex,
        flags=re.DOTALL | re.IGNORECASE
    )
    # 极简版：一键修复所有带 # 号的十六进制颜色
    latex = re.sub(r'color\{#([0-9a-fA-F]{6})\}', r'color[HTML]{\1}', latex)
    # 3. 兜底处理手写的 HTML 下划线标签: <u>内容</u>
    # 兼容 &lt;u&gt;、<U>、<u > 等一切变体
    latex = re.sub(
        r'(?:<|&lt;)u[^>]*?(?:>|&gt;)(.*?)(?:</|&lt;/)u(?:>|&gt;)',
        r'\\uline{\1}',
        latex,
        flags=re.DOTALL | re.IGNORECASE
    )

    latex = re.sub(
        r'(?:<|&lt;)i[^>]*?(?:>|&gt;)(.*?)(?:</|&lt;/)i(?:>|&gt;)',
        r'\\textit{\1}',
        latex,
        flags=re.DOTALL | re.IGNORECASE
    )

    latex = re.sub(
        r'(?:<|&lt;)label(?:>|&gt;)(.*?)(?:</|&lt;/)label(?:>|&gt;)',
        r'\\ref{\1}',
        latex,
        flags=re.DOTALL | re.IGNORECASE
    )
    # =================================================================
    latex = re.sub(r'\\tag\{([^}]+)\}', r'\\label{\1}', latex)

    # 4. 处理自定义的 <text> 标签：脱去标签，仅保留纯文本
    # =================================================================
    for key, val in raw_texts.items():
        latex = latex.replace(key, val)

    # =================================================================
    # 【核心修复2】：将刚才插进去的路标，替换为真正的双回车（LaTeX 语法中的新段落）
    # =================================================================
    latex = latex.replace('SAFEPARABREAK', '\n\n')

    # 顺手优化：如果你在 $$ 后面没留空行，强行补一个单回车。
    # 这样 LaTeX 渲染时依然是“同一段落”（不缩进），但源码不会恶心地挤在一行报错。
    latex = re.sub(r'\$\$(?=[^\n])', r'$$\n', latex)

    # 删除 $$ 前面（上面）的多余空行，保持公式与上文紧凑
    # latex = re.sub(r'\n\s*\n\s*\$\$', r'\n$$', latex)

    # 注意：删除 $$ 后面空行的代码依然保持注释状态，这样就能原汁原味保留你的排版意图！
    # latex = re.sub(r'\$\$\s*\n\s*\n', r'$$\n', latex)
    # ---------------------------------------------------------------------
    # latex = re.sub(r'\n\s*\n\s*\$\$', r'\n$$', latex)  # 删掉 $$ 前面的多余换行
    # latex = re.sub(r'\$\$\s*\n\s*\n', r'$$\n', latex)  # 删掉 $$ 后面的多余换行
    # =================================================================
    # 【新增修复】：强行保护移动参数（caption/section）中的公式，防止崩溃
    # =================================================================
    def protect_moving_arg(match):
        cmd = match.group(1)
        content = match.group(2)
        # 绝对不能保护 $！因为 caption 支持 $ $。
        # 仅保护可能在图表目录生成时导致崩溃的脆弱指令
        protected = content.replace(r'\operatorname', r'\protect\operatorname') \
            .replace(r'\boldsymbol', r'\protect\boldsymbol') \
            .replace(r'\frac', r'\protect\frac')
        return f'\\{cmd}{{{protected}}}'

    latex = re.sub(r'\\(caption|section|subsection|subsubsection)\{((?:[^{}]|\{[^{}]*\})*)\}', protect_moving_arg,
                   latex)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(latex)


if __name__ == "__main__":
    md_file_path = Path(INPUT_MD_FILE)
    file_dir = md_file_path.parent

    # 设定配置文件路径（默认在该 md 文件同级目录下寻找）
    customer_convert_config_path = file_dir / "customer_convert_config.yaml"

    # 处理输出路径，并确保目标文件夹存在
    if OUTPUT_TEX_FILE.strip():
        output_path = Path(OUTPUT_TEX_FILE)
        output_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        output_path = md_file_path.with_suffix('.tex')

    # 执行转换
    convert(md_path=md_file_path,
            customer_convert_config_path=customer_convert_config_path,
            output_path=output_path)