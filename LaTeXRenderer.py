import mistune
from urllib.parse import unquote


# 用于对解析到的Markdown元素进行转换，转化为LaTeX


class LaTeXRender(mistune.BaseRenderer):
    def __init__(self, my_config, escape=True, allow_harmful_protocols=None):
        super(LaTeXRender, self).__init__()
        self._allow_harmful_protocols = allow_harmful_protocols
        self._escape = escape
        self.my_config = my_config
        self.table_template_file = ""
        self.table_template_text = ""
        self.image_template = ""

    def render_token(self, token, state):
        # backward compitable with v2
        func = self._get_method(token['type'])
        attrs = token.get('attrs')

        if 'raw' in token:
            text = token['raw']
        elif 'children' in token:
            text = self.render_tokens(token['children'], state)
        else:
            if attrs:
                return func(**attrs)
            else:
                return func()
        if attrs:
            return func(text, **attrs)
        else:
            return func(text)

    ###########################

    ### inline level ###

    # 普通文本
    # 普通文本
    def text(self, text: str) -> str:
        # 仅在这里转义 LaTeX 特殊字符，不会影响公式和标题
        text = text.replace('#', r'\#').replace('&', r'\&').replace('%', r'\%')
        t = self.my_config["text"]
        t = t.replace("<text>", text)
        return t

    # *强调*
    def emphasis(self, text):
        return text

    # **加粗**
    def strong(self, text):
        t = self.my_config["strong"]
        t = t.replace("<text>", text)
        return t

    # 链接[text](url "title")
    def link(self, text: str, url: str, title="链接") -> str:
        t = self.my_config["link"]
        t = t.replace("<text>", text)
        t = t.replace("<url>", unquote(url))
        t = t.replace("<title>", title)
        return t

    # 图像![alt](url "title")
    # 图像![alt](url "title")
    def image(self, alt: str, url: str, title="图片") -> str:
        from pathlib import Path
        from urllib.parse import unquote
        import re

        url = unquote(url)
        filename = Path(url).name
        final_url = f"images/{filename}"

        scale = "0.95"
        raw_caption = filename

        if alt:
            alt = alt.strip()
            scale_match = re.match(r'^\s*\(\s*([0-9.]+)\s*\)\s*@\s*(.*)', alt)
            if scale_match:
                scale = scale_match.group(1)
                raw_caption = scale_match.group(2).strip()
            else:
                raw_caption = alt

        # ==========================================
        # 1. 处理 caption: 允许存在 $ $，但要智能转义 _
        # ==========================================
        def escape_text_outside_math(text):
            if not text: return "img"
            # 按照 $$...$$ 或 $...$ 将文本切块
            parts = re.split(r'(\$\$.*?\$\$|\$.*?\$)', text)
            for i in range(0, len(parts), 2):  # 偶数索引部分一定是纯文本
                parts[i] = parts[i].replace('_', r'\_').replace('%', r'\%').replace('&', r'\&')
            return "".join(parts)

        safe_caption = escape_text_outside_math(raw_caption)

        # ==========================================
        # 2. 处理 label: 严禁出现 $ \ _ 等特殊字符，全部转为 @
        # ==========================================
        if raw_caption:
            # 仅保留中英文和数字，其余所有符号（包含 $ \ _ { }）统统替换为 @
            safe_label = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5]', '@', raw_caption)
            # 把连续的 @ 合并为一个，并去掉首尾多余的 @
            safe_label = re.sub(r'@+', '@', safe_label).strip('@')
        else:
            safe_label = "img"

        if not safe_label:
            safe_label = "img"

        t = self.my_config["image"]
        t = t.replace("<url>", final_url)
        t = t.replace("<alt>", safe_caption)  # 填入安全的 caption
        t = t.replace("<label>", safe_label)  # 填入转化为 @ 的 label
        t = t.replace("<scale>", scale)

        return t
    # `行内代码`
    def codespan(self, text: str) -> str:
        t = self.my_config["codespan"]
        t = t.replace("<text>", text)
        return t

    def linebreak(self) -> str:
        t = self.my_config["linebreak"]
        return t

    def softbreak(self) -> str:
        t = self.my_config["softbreak"]
        return t

    # 行内HTML
        # 行内HTML
    def inline_html(self, html: str) -> str:
        # 直接原样返回 HTML 标签，留给 convert.py 末尾的正则进行全局替换！
        return html


    ### block level ###

    # 段落
    # 段落
    def paragraph(self, text: str) -> str:
        import re as _re
        text = text.strip()
        # 移除段落开头和结尾的 \\，防止 LaTeX 报错
        if text.startswith(r'\\'):
            text = text[2:].strip()
        if text.endswith(r'\\'):
            text = text[:-2].strip()

        # 修复：还原 $...$、$$...$$ 内被 text() 错误转义的 \& → &
        # mistune 有时把块公式当 inline_math 处理（在列表项内），
        # 此时公式内部已经被 text() 转义了 &，需要在段落级别修复。
        def restore_math_escapes(s):
            # 匹配 $$...$$（多行）
            def fix(m):
                return m.group(0).replace(r'\&', '&')

            s = _re.sub(r'\$\$.*?\$\$', fix, s, flags=_re.DOTALL)
            s = _re.sub(r'\$[^$\n]+?\$', fix, s)
            return s

        text = restore_math_escapes(text)

        t = self.my_config["paragraph"]
        t = t.replace("<text>", text)
        # 【核心修复】：强制在段落末尾加上双回车（空行），确立 LaTeX 段落边界
        return t.strip() + "\n\n"

    # 标题
    def heading(self, text: str, level: int, **attrs) -> str:
        heading_types = [
            "chapter",
            "section",
            "subsection",
            "subsubsection",
            "paragraph",
            "subparagraph"
        ]
        t = self.my_config["heading"]
        t = t.replace("<text>", text)
        t = t.replace("<heading_types>", heading_types[level - 1])
        return t.strip() + "\n\n"

    def blank_line(self) -> str:
        t = self.my_config["blank_line"]
        return t

    def thematic_break(self) -> str:
        t = self.my_config["thematic_break"]
        return t

    def block_text(self, text: str) -> str:
        t = self.my_config["block_text"]
        t = t.replace("<text>", text)
        return t

    def block_quote(self, text: str) -> str:
        import re

        # 去除前后的空白，方便正则匹配
        stripped = text.strip()

        # 正则匹配 Obsidian Callout 语法: [!type] title
        # 提取括号里的原名 (group 1) 和 后面的标题 (group 2)
        pattern = r'^\[!([a-zA-Z0-9_-]+)\]([^\n]*)(?:\n(.*))?'
        match = re.match(pattern, stripped, flags=re.DOTALL)

        if match:
            # 100% 信任原名，不做任何转换或映射
            callout_type = match.group(1)
            title = match.group(2).strip()
            content = match.group(3).strip() if match.group(3) else ""

            # 直接拼接为 LaTeX 环境
            if title:
                return f"\n\\begin{{{callout_type}}}[{title}]\n{content}\n\\end{{{callout_type}}}\n"
            else:
                return f"\n\\begin{{{callout_type}}}\n{content}\n\\end{{{callout_type}}}\n"

        # 如果不是 [!xxx] 开头的 Callout，就按普通的引用块处理
        t = self.my_config.get("block_quote", "\\begin{quote}\n<text>\n\\end{quote}\n")
        t = t.replace("<text>", text)
        return t

    # def block_quote(self, text: str) -> str:
    #     t = self.my_config["block_quote"]
    #     t = t.replace("<text>", text)
    #     return t

    def block_html(self, html: str) -> str:
        # 同理，块级 HTML 也原样保留
        return html


    def block_error(self, text: str) -> str:
        raise NotImplementedError()

    def list(self, text: str, ordered: bool, **attrs) -> str:
        if ordered:
            t = self.ordered_list(text, **attrs)
        else:
            t = self.disordered_list(text, **attrs)
        return t.strip() + "\n\n"

    def ordered_list(self, text: str, **attrs) -> str:
        t = self.my_config["ordered_list"]
        t = t.replace("<text>", text)
        return t.strip() + "\n\n"

    def disordered_list(self, text: str, **attrs) -> str:
        t = self.my_config["disordered_list"]
        t = t.replace("<text>", text)
        return t.strip() + "\n\n"

    def list_item(self, text: str) -> str:
        t = self.my_config["list_item"]
        t = t.replace("<text>", text)
        return t

    ### provide by math plugin ###

    # 判断公式内容是否含有 aligned/cases 等环境或 \tag，
    # 这类公式不能被 \begin{equation} 套住（amsmath 报错），
    # 必须直接用 $$...$$ 输出。
    def _math_needs_dollar(self, text: str) -> bool:
        dangerous = [r'\begin{aligned}', r'\begin{cases}',
                     r'\begin{gather}', r'\begin{align}', r'\tag{']
        for d in dangerous:
            if d in text:
                return True
        return False

    # 行间公式
    def block_math(self, text):
        # 无论公式多简单或多复杂，一律使用 $$ 包裹
        # 这样生成的 .tex 就会是 $$ ... $$ 格式
        return '$$\n' + text.strip() + '\n$$\n\n'

    # 代码块 ```language
    def block_code(self, code: str, info=None) -> str:
        # 默认语言兜底为 text
        lang = "text"

        if info:
            # 剥离可能存在的换行符和空格
            info = info.strip()
            # 智能兼容：去掉可能存在的 { }，例如把 {python} 变成 python
            lang = info.strip('{}').strip()

        t = self.my_config["block_code"]

        # 注入语言和代码正文
        t = t.replace("<lang>", lang)
        t = t.replace("<code>", code.strip())

        return f"\n{t}\n"
    # 行内公式
    def inline_math(self, text):
        # 如果 inline_math 的内容实际上是块级公式（含换行、子环境、\tag），
        # 说明 mistune 把列表项内的 $$...$$ 当成了 inline_math，
        # 此时强制以 $$...$$ 块输出，不能用行内 $...$。
        if '\n' in text or self._math_needs_dollar(text):
            # 还原被 text() 转义的 & 和 %
            text = text.replace(r'\&', '&')
            return '$$\n' + text.strip() + '\n$$'
        t = self.my_config["inline_math"]
        t = t.replace("<text>", text)
        return t

    ### provide by table plugin ###

    # 将一行 ||| 分隔的单元格文本转换为 LaTeX 行
    def _row_to_latex(self, row_text):
        cells = [c for c in row_text.rstrip("\n").split("|||") if c != ""]
        return " & ".join(cells) + "\\\\"

    # 表格：text = "HEAD_MARKER\n<head行>\nBODY_MARKER\n<body各行>"
    def table(self, text):
        HEAD_MARKER = "%%TABLE_HEAD%%\n"
        BODY_MARKER = "%%TABLE_BODY%%\n"

        head_start = text.find(HEAD_MARKER)
        body_start = text.find(BODY_MARKER)

        # --- 新增安全保护 ---
        if head_start == -1 or body_start == -1:
            # 如果没找到标记位，直接返回原始内容，避免后续切割报错
            return text
        # ------------------

        head_text = text[head_start + len(HEAD_MARKER): body_start]

        body_text = text[body_start + len(BODY_MARKER):]

        # 解析表头：取第一行非空行
        head_rows = [r for r in head_text.strip().split("\n") if r.strip()]
        head_latex = self._row_to_latex(head_rows[0]) if head_rows else ""

        # 推断列数
        col_count = len([c for c in head_rows[0].split("|||") if c != ""]) if head_rows else 1
        align = "c" * col_count

        # 解析表体：每行转换为 LaTeX 行
        body_rows = [r for r in body_text.strip().split("\n") if r.strip()]
        body_lines = [self._row_to_latex(r) for r in body_rows]
        body_latex = "\n        ".join(body_lines)

        t = self.my_config["table"]
        t = t.replace("<head>", head_latex)
        t = t.replace("<align>", align)
        t = t.replace("<body>", body_latex)
        return t.strip() + "\n\n"

    def table_head(self, text):
        # 在 head 前插入标记，让 table() 能定位 head 区域
        return "%%TABLE_HEAD%%\n" + text

    def table_body(self, text):
        # 在 body 前插入标记，让 table() 能定位 body 区域
        return "%%TABLE_BODY%%\n" + text

    def table_row(self, text):
        # text 是该行所有 table_cell 的拼接，末尾有多余的 |||，去掉后换行
        return text.rstrip("|||").rstrip() + "\n"

    def table_cell(self, text, align=None, head=False):
        return text + "|||"

        # ++下划线++ 或 <u>下划线</u> 的渲染
    def underline(self, text: str) -> str:
        # 获取配置，如果没有配则使用默认的 \uline
        t = self.my_config.get("underline", r"\uline{<text>}")
        t = t.replace("<text>", text)
        return t