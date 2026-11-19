# 从阅读抽屉理解模态界面的焦点生命周期

这次前端把页面底部的文档阅读器改成了侧边抽屉。点击答案的引用后，可以核对原文，再关闭抽屉继续提问。值得学习的是：浮层位置可以靠 CSS 完成，但“进入阅读、限制操作范围、返回原处”需要完整的交互生命周期。

已核对你的《Helix B CSS：布局、滚动与层级管理》和《React children：传递与渲染子内容》：已有内容介绍了层级、滚动、Portal 和内容组合；这里补充它们尚未覆盖的焦点管理。

## 是什么：让操作范围与视觉范围一致

键盘焦点表示“下一次键盘操作会作用到哪里”，可以通过 `document.activeElement` 查看。模态界面打开后，用户应先在其中操作；关闭后再回到原来的工作流。

本项目把几个职责分开处理：

| 机制 | 本次作用 |
| --- | --- |
| 遮罩与固定定位 | 表达当前正在阅读资料，形成视觉层次 |
| `role="dialog"`、`aria-modal="true"`、名称 | 向辅助技术说明这是有名称的模态对话框 |
| 背景 `inert` | 阻止背景内容被点击、聚焦，并将其移出辅助技术的访问范围 |
| 焦点进入、Tab 循环、关闭后恢复 | 建立连续的键盘操作路径 |
| `body.style.overflow = 'hidden'` | 暂停背景页面滚动 |

`aria-modal` 只声明语义，不会自动实现模态行为。遮罩阻挡鼠标，也不代表键盘焦点不会进入背景；锁定滚动同样不能代替焦点管理。[MDN：aria-modal](https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Reference/Attributes/aria-modal)

## 为什么需要：核对原文后能继续原来的问题

假设焦点还停在被遮住的引用按钮上，用户按 Tab，可能会进入背景的搜索框，却看不到正在操作哪里。关闭抽屉时若焦点落到页面主体，键盘用户又要重新寻找刚才的答案。

`ReaderDrawer.tsx` 在打开时保存原焦点，给 `.workspace-shell` 添加 `inert`，并把焦点移入抽屉。`DocumentReader.tsx` 则在异步加载完成后聚焦阅读区域并滚动到内容。关闭时，抽屉先解除背景隔离，再把焦点还给仍存在的触发控件。

注意结构：自定义抽屉位于 `.workspace-shell` 外面。普通元素放在 `inert` 的祖先内部，也会一起失去交互能力。[MDN：inert](https://developer.mozilla.org/en-US/docs/Web/HTML/Global_attributes/inert)

## 如何使用：把打开与清理写成对应关系

下面是本次生命周期的缩小示例，假设已取得抽屉和背景节点；完整版本还包含键盘监听与原有属性的保存。

```tsx
useEffect(() => {
  const previous = document.activeElement
  const overflow = document.body.style.overflow
  const wasInert = background.hasAttribute('inert')

  background.setAttribute('inert', '')
  document.body.style.overflow = 'hidden'
  drawer.focus({ preventScroll: true })

  return () => {
    document.body.style.overflow = overflow
    if (!wasInert) background.removeAttribute('inert')
    if (previous instanceof HTMLElement && previous.isConnected) {
      previous.focus({ preventScroll: true })
    }
  }
}, [])
```

焦点入口使用 `tabIndex={-1}`：代码可以主动聚焦它，但它不会额外占据普通 Tab 顺序。`preventScroll` 用来避免恢复焦点时把背景页面带到意外的位置；阅读内容的定位由阅读器自行完成。

Tab 循环的核心规则很小：最后一个控件按 Tab 回到第一个；第一个按 Shift + Tab 回到最后一个。抽屉还处理 Escape，并保留可见的关闭按钮。[WAI：Modal Dialog Pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)

`reader-drawer.test.tsx` 在 `StrictMode` 下验证了循环、Escape、背景隔离和焦点恢复。React 开发模式会额外执行一次 Effect 的 setup → cleanup；因此添加监听必须对应移除监听，修改滚动和 `inert` 必须对应恢复，而不是在清理时无条件写死默认值。[React：useEffect](https://react.dev/reference/react/useEffect)

## 何时使用，以及本次实现的边界

这种模式适用于需要暂时集中操作、随后回到上下文的资料核对、编辑和确认窗口。如果产品需要同时操作两边，就应采用非模态面板，不能仍给背景加 `inert`。

新组件设计时，值得先了解原生 `<dialog>`：通过 `showModal()` 打开时，浏览器提供背景隔离、初始聚焦和默认 Escape 关闭等行为；单独添加 `open` 属性不会得到同样的模态行为。本次现有抽屉采用自定义实现，需要自行维护这些职责。[MDN：dialog](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/dialog)

本次选择器覆盖当前阅读器中的控件，不是完整的通用焦点算法。以后加入 CSS 隐藏控件、复杂 `tabindex`、嵌套弹窗或 Shadow DOM，需要重新检查。PDF fallback 的 iframe 是独立浏览上下文，内部按键不一定传到父页面，也应在真实浏览器中验证。组件测试能保护已定义的行为，但不能替代屏幕阅读器和全部浏览器验证。

触发元素如果已经被删除，`isConnected` 检查只会跳过恢复；若将来增加删除文档等操作，还要明确下一个合理焦点，例如资料列表标题。

## 学习范围与理解检查

现在先掌握：视觉遮罩与交互隔离不同、焦点进入与恢复必须成对、Effect 的外部改动需要清理。以后再深入原生 dialog 的 top layer、通用 tabbable 算法、嵌套模态管理和屏幕阅读器测试。

1. 去掉 `inert`，但保留遮罩和 `overflow: hidden`，哪些用户仍可能操作背景？如何用键盘复现？
2. 关闭抽屉后，为什么先解除 `inert` 再恢复焦点？如果引用按钮已经不存在，应选择什么替代位置？

建议新建笔记《React 模态界面：焦点管理、inert 与 Effect 清理》，提纲为“视觉与语义 → 打开/关闭生命周期 → Tab 与 Escape → StrictMode 清理 → 真实浏览器边界”；也可在现有 CSS 笔记的“可访问性考虑”处链接到它。正式笔记由你手工整理，本材料不修改笔记目录。
