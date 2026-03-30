# GitHub SONiC Monitor

每日自动监控 sonic-net 组织和 FRRouting/frr 的 GitHub 活动，生成结构化报告。

## 监控范围

- **sonic-net 组织**: 50★ 以上的仓库（12 个）
- **额外监控**: sonic-platform-daemons（35★）
- **FRRouting**: frr（4070★）

总计 **14 个仓库**，相比原 47 个减少 70%。

## 优化特性

1. **减少子代理**: 2 个并行扫描（原 4 个）
2. **缩小范围**: 50★以上 + 指定仓库
3. **增量扫描**: 基于仓库更新时间缓存
4. **缓存机制**: 本地 JSON 缓存，避免重复扫描

## 运行方式

### 自动运行
每天 UTC 06:00（北京时间 14:00）自动执行。

### 手动触发
在 Actions 页面点击 "Run workflow" 按钮。

## 报告输出

- Markdown 格式报告保存到 `reports/` 目录
- 缓存文件保存到 `cache/` 目录
- 支持钉钉文档上传（需配置）

## 配置

在仓库 Settings -> Secrets 中配置：

| Secret | 说明 | 必需 |
|--------|------|------|
| `GITHUB_TOKEN` | GitHub Personal Access Token | 是 |
| `DINGTALK_WEBHOOK` | 钉钉机器人 Webhook | 否 |
| `XIAOQ_API_KEY` | 小Q API Key | 否 |

## 本地运行

```bash
# 安装依赖
pip install requests

# 设置环境变量
export GITHUB_TOKEN=your_token_here

# 运行
python scripts/github_monitor.py
```

## License

MIT
