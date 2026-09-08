# 桌面更新检查与安装

- 应用打开后延迟 10 秒检查；过去 24 小时内有成功检查结果时复用缓存。
- 长时间运行每 24 小时补查一次。系统唤醒、页面重新可见或网络恢复时检查是否已到期。
- 后台失败保留上次结果，不弹窗；按 1、2、4、6 小时间隔重试，之后最多每 6 小时一次。
- “关于”页始终提供手动检查，不受缓存时限限制；手动失败显示错误。
- 新版本只通过“关于”旁的小圆点及页面内更新按钮提示，不自动下载、不自动安装。
- 用户下载更新后，校验完成进入等待安装状态。点击“安装并重启”列出将停止的服务；用户确认后才启动安装助手。若服务列表已变化，需重新查看并确认。

## 代码职责

`useAppUpdates` 在根组件中提供唯一共享实例并管理生命周期；路由切换不重建状态，也不终止更新进度跟踪。

- `updates/useUpdateChecks`：版本信息、手动/自动检查、并发请求合并、错误与代理设置。
- `updates/updateScheduler`：启动延迟、24 小时调度、失败退避、唤醒与定时器清理；时钟可注入测试。
- `updates/useUpdateInstaller`：下载进度、待安装状态、服务影响预览和显式安装确认。
- `AboutRouteView`、`AboutView`、`AppSidebar`、`UpdateInstallDialog`：消费 composable 状态、展示、发出用户操作事件。

成功检查缓存在桌面设置目录的 `update-check.json`，通过原子写入保存。缓存与当前应用版本、下载代理、平台绑定；损坏或未来时间戳视作未命中。缓存不放在 WebView localStorage，避免桌面 HTTP 端口变化导致跨重启丢失。

后台只缓存检查元数据。安装仍由现有下载器执行下载和 SHA-256 校验；真实程序路径、服务配置和 OAuth 数据不进入更新检查缓存。

## 验证

```sh
cd agent_workbench/web
npm test
npm run build
```

仓库根目录运行：

```sh
.venv/bin/python -m unittest tests.test_update_checking tests.test_updates tests.test_desktop_api
```

前端测试使用注入时钟验证时间与竞态，不等待真实的 24 小时；后端测试覆盖跨实例缓存、版本/代理/平台变化、缓存损坏、检查失败、并发请求和安装时服务变化。
