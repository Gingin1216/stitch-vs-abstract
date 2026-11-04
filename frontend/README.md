# 前端（P4）

技术栈：React + Vite + TypeScript。

接口契约见根目录 `API.md` §4。默认使用 Mock 数据，不依赖后端；通过
`VITE_API_MODE=remote` 切换真实接口。

## 本地运行

```bash
npm install
npm run dev
```

默认地址：`http://localhost:5173`

## 校验

```bash
npm test
npm run test:e2e
npm run build
```

Playwright 默认调用本机 Microsoft Edge，覆盖 1440px 桌面和 375px 手机视口。

## 数据模式

```bash
# 默认，使用共享 Mock 的隔离适配
npm run dev

# 真实接口，开发服务器将 /api 代理到 localhost:8001
$env:VITE_API_MODE="remote"
npm run dev
```

如需指定完整 API 地址，可设置 `VITE_API_BASE_URL`。

当前范围包含开局页、五回合对局页和终局战报页。战报页会展示胜负、
崩坏曲线、最终故事与 AI 解说，并可通过 Canvas 下载 PNG 海报。

## 页面结构

1. **开局页**：选模式（双人同屏 / 人机对战）→ `POST /api/game`
2. **对局页**（核心，全部表现力砸在这里）：
   - 顶部：崩坏度进度条（0-100，红蓝渐变，随每次判卷动画滑动）
   - 中部：当前故事句子（打字机效果出现）+ 回合数 / 当前行动方
   - 下部：5 张词卡（普通词灰、抽象词紫、违禁词红色警告边框），点击 → `POST /pick`
   - 判卷结果：弹幕式弹出 AI 评语 + 得分动画
3. **战报页**：`GET /report` → 崩坏度曲线图 + 最终故事 + 刘看山解说 + **Canvas 生成战报海报**（可下载，直接当提交海报底稿）

## 演示视频素材清单（边开发边录）

- 人机模式完整一局（重点录违禁词回合的评语）
- 双人对战精华 30 秒
- 崩坏度条来回拉扯的拉锯战片段
