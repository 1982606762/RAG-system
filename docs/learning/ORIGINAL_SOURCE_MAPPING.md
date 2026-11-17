# RAG 引用的来源映射：从片段回到原件

本材料对应第一版的原文定位改动。已检索本地笔记，并阅读 React children、React 闭包与 useRef、数据导入与版本留存的相关笔记；它们尚未覆盖这里的来源映射。建议新建一篇笔记，正式笔记仍由你手工整理。

## 是什么：给每个位置说明“相对于哪里”

来源映射是一条可追踪的路径：**命中片段 → 解析内容块 → 原文件范围**。

| 本次字段 | 回答的问题 |
| --- | --- |
| `chunk.sources` | 片段用了哪个内容块，以及 `block.text` 的哪一段？ |
| `Block.location` | 这个内容块对应原件的哪些字符，或哪一页的哪个区域？ |

两个范围独立保存，因为解析会改变表示。原件 `## 维护` 的标题块可能只有 `维护`；Markdown 表格的分隔线也会从解析文本中移除。此时解析文本中的第 0 个字符，无法直接解释为原件的第 0 个字符。

## 为什么需要：让引用可以核对

此前点击来源只能找到提取内容。现在要打开 TXT/Markdown 原段落，以及 PDF 页面上的对应区域，必须保留解析前的位置。

本次本地解析器逐行记录原件范围，再生成块：标题范围包含 `##`，表格范围包含原始分隔线。它提供的是**块级定位**，没有声称能把块内每个字符一一映射回原件。这种精度已能帮助核对，也避免为第一版建立复杂的逐字符映射表。

这个知识点值得学习，因为清洗、OCR、摘要和翻译都会改变文本；区分位置的参照对象，能避免“结果看起来正确，引用却指错地方”的隐蔽错误。

## 如何使用：先约定文本单位

本次文本范围采用 `[start, end)`：包含起点，不包含终点；对象是去掉 UTF-8 BOM、保留 CRLF 的解码文本。Python `str` 按 Unicode code points 表示文本。[Python 3.11 文档](https://docs.python.org/3.11/library/stdtypes.html#text-sequence-type-str)

```python
text = "😀\r\n维护"
start, end = 3, 5
assert text[start:end] == "维护"
```

JavaScript 普通字符串切片按 UTF-16 code units 计数，`😀` 占两个单位。本次 `OriginalText` 先用字符串迭代得到 code points，才应用后端偏移：

```javascript
const text = "😀\r\n维护";
Array.from(text).slice(3, 5).join(""); // "维护"
text.slice(3, 5);                    // "\n维"，单位不一致
```

字符串迭代保留代理对，但不会把组合字符或整组 emoji 合成一个“视觉字符”。这里追求的是与 Python 的计数一致。[MDN 字符串迭代说明](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/String/Symbol.iterator)

如果前端擅自把 `\r\n` 换成 `\n`，即使 code points 已对齐，后续范围仍会偏移。因此解码和换行规则也是接口契约的一部分。

## PDF 中如何应用同一原则

PDF 的位置需要额外约定原点、单位和显示区域。本次 `displayed_cropbox` 先处理裁剪范围与旋转，`pdf_location` 再转为左上角原点的 `[0, 1]` 坐标：

```python
left_fraction = (x0 - crop_left) / (crop_right - crop_left)
```

例如左右边界为 `0.1` 和 `0.6`，前端框的位置就是 `left: 10%`、`width: 50%`。这样页面缩放后仍能对齐。只交换旋转页的宽高不够：非对称裁剪的原点也会移动。PDFium 的有效页面范围由 media box 与 crop box 的交集决定。[pypdfium2 文档](https://pypdfium2.readthedocs.io/en/stable/python_api.html#pypdfium2.PdfPage.get_bbox)

测试没有只比较两组计算结果，而是渲染带裁剪与旋转的 PDF，检查文字像素是否落在来源框内。这能发现双方共同沿用错误坐标假设的问题。

## 何时使用，以及边界

搜索结果、AI 答案引用、OCR 校对都适合保留这条映射链。原件须与映射对应；原件或解析方式改变后，需要重新生成或明确关联版本。

Google 解析可能改写或重排文本，因此当前只给唯一、完全一致的文本匹配保存范围；重复文本或改写内容不猜位置。旧资料无位置时回退到提取块，PDF 无可靠区域时只打开来源页。定位精度应由证据决定。

PDF 页面预览另用子进程运行，因为 PDFium 不保证线程安全；这属于运行隔离，不会自动修正坐标。[pypdfium2 线程说明](https://pypdfium2.readthedocs.io/en/stable/python_api.html#thread-incompatibility)

## 学习范围与理解检查

现在必须理解：两种范围的区别、半开区间、code points 与 UTF-16、裁剪坐标原点、缺少映射时的回退。以后再深入逐字符映射、表格行级区域、grapheme clusters，以及跨解析版本的长期引用。

1. 原件有两处“每月清洁滤网”，解析器只返回一次。为什么仅用 `find()` 的首个结果不能证明来源？
2. 将示例的 CRLF 改为 LF，原来的 `start=3` 还能复用吗？分别在 Python 和 JavaScript 验证。

建议笔记标题：**《RAG 来源映射：文本偏移、PDF 坐标与可靠回退》**。提纲：映射链 → 表示变化 → 文本单位契约 → PDF 坐标转换 → 回退与版本 → 用原件验证映射。
