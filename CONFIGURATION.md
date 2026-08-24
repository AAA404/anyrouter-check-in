# 双账号配置

本文档用于配置两个账号：

- AnyRouter：使用 AnyRouter 的 `session` Cookie 登录。
- AgentRouter：使用已登录 GitHub 的 Cookie 完成 GitHub OAuth 登录。

两个账号都放在同一个 GitHub Actions Secret：`ANYROUTER_ACCOUNTS`。

## 1. 准备 AnyRouter 信息

### 获取 session Cookie

1. 在浏览器打开 [AnyRouter](https://anyrouter.top/) 并登录。
2. 打开开发者工具，进入 **Application / 存储** -> **Cookies**。
3. 选择 `https://anyrouter.top`，复制 `session` 的值。
4. 建议重新登录后再复制，Cookie 失效后需要重新获取。

### 获取 api_user

1. 在开发者工具中进入 **Network / 网络**，过滤 `Fetch/XHR`。
2. 打开任意需要登录的 AnyRouter 页面，查看请求头。
3. 找到 `New-Api-User` 请求头，复制它的值。

`api_user` 必须与该 session 属于同一个 AnyRouter 账号。不要填写登录页面显示的用户名，也不要填写 GitHub 用户 ID。

## 2. 准备 AgentRouter 的 GitHub Cookie

1. 在浏览器登录 GitHub，并确认能访问 [GitHub Profile Settings](https://github.com/settings/profile)。
2. 使用浏览器 Cookie 导出工具导出 GitHub Cookie。
3. 保留 JSON 数组格式，至少应包含有效的 `user_session` 和 `logged_in` Cookie；最稳妥的做法是导出 GitHub 的完整 Cookie JSON。
4. Cookie 的 `domain` 应为 `github.com` 或 `.github.com`。导出文件中属于其他域名的 Cookie 不要放入配置。

GitHub Cookie 是登录凭据，等同于账号密钥。不要提交到仓库、写入 `.env`、发送到聊天或打印到日志。Cookie 失效后，重新导出并更新 Secret 即可。

## 3. ANYROUTER_ACCOUNTS 完整示例

将下面的 JSON 中占位符替换成真实值，然后作为一个整体保存到 GitHub Environment Secret `ANYROUTER_ACCOUNTS`：

```json
[
  {
    "name": "AnyRouter session",
    "provider": "anyrouter",
    "cookies": {
      "session": "替换为 AnyRouter 的 session Cookie"
    },
    "api_user": "替换为 New-Api-User 请求头的值"
  },
  {
    "name": "AgentRouter GitHub",
    "provider": "agentrouter",
    "github_cookies": [
      {
        "name": "user_session",
        "value": "替换为 GitHub user_session Cookie",
        "domain": ".github.com",
        "path": "/"
      },
      {
        "name": "logged_in",
        "value": "yes",
        "domain": ".github.com",
        "path": "/"
      }
    ]
  }
]
```

如果使用 Cookie 导出工具生成的完整 JSON，请将第二个账号的 `github_cookies` 数组整体替换为导出的数组，不要只保留示例中的两个条目。运行时会自动剥离 `expires`、`sameSite` 等浏览器专用元数据，只注入 OAuth 所需的 Cookie 名称、值、域名和路径。

配置规则：

- 最外层必须是 JSON 数组 `[...]`。
- 每个账号必须是 JSON 对象。
- JSON 使用双引号，不要使用单引号、注释或末尾逗号。
- AnyRouter 账号必须同时有 `cookies.session` 和 `api_user`。
- AgentRouter 账号必须有 `provider: "agentrouter"` 和 `github_cookies`；不需要 `email`、`password`、`cookies` 或 `api_user`。
- `name` 仅用于日志和通知，可以自行修改。

## 4. 配置 GitHub Environment Secret

仓库中当前 workflow 使用名为 `production` 的 GitHub Environment：

1. 打开仓库 **Settings** -> **Environments**。
2. 创建或进入名为 `production` 的 Environment。
3. 在 **Environment secrets** 中新增 Secret：
   - Name：`ANYROUTER_ACCOUNTS`
   - Value：上面的完整 JSON

AgentRouter 的 GitHub OAuth 和 WAF 对 GitHub Actions 出口 IP 较敏感，建议在同一个 `production` Environment 中再添加：

- Name：`PROXY_SUBSCRIPTION_URL`
- Value：你的 Clash/Mihomo 订阅地址

仓库 workflow 会自动启动代理，并对 `agentrouter` 使用代理；AnyRouter 默认不使用代理。当前 workflow 使用 AgentRouter 官方备用域名 `https://ps.air-outer.com`，并同时探测该域名和 Google，避免选中只能访问 Google、却会被 AgentRouter 关闭连接的代理节点。也可以用 `AGENTROUTER_DOMAIN` 覆盖入口；它的优先级高于 `PROVIDERS` 中的同名 `domain`。没有可用代理时，AnyRouter 仍可签到，但 AgentRouter 会明确失败并提示代理不可用。

如果订阅中的节点在 GitHub Actions Runner 上全部超时，建议改用一个 Runner 可直接访问的代理出口。在 `production` Environment Secrets 中添加 `CHECKIN_PROXY_URL`，值填写完整的 HTTP 代理地址，例如 `http://user:password@proxy.example.com:8080`。workflow 会优先验证这个地址，验证成功后不再扫描 `PROXY_SUBSCRIPTION_URL` 中的节点；验证失败时才回退到订阅节点。不要把代理地址提交到仓库或普通变量中。

AgentRouter 默认不再启动 Chromium；`CHECKIN_HEADLESS_AGENTROUTER` 和 `CHECKIN_HUMANIZE_AGENTROUTER` 只在显式启用浏览器回退时生效。AnyRouter 仍使用全局 `CHECKIN_HEADLESS` 和 `CHECKIN_HUMANIZE` 设置。

AgentRouter 登录默认通过 HTTP 客户端完成公开的 GitHub OAuth 流程，以绕开 GitHub Actions 代理出口下 Chromium 的 `ERR_CONNECTION_CLOSED`。GitHub Cookie 只发送给 GitHub，OAuth state/session 只保存在 AgentRouter 客户端中。若需排障，可设置 `CHECKIN_AGENTROUTER_BROWSER_FALLBACK=true` 启用旧的浏览器回退，并通过 `CHECKIN_AGENTROUTER_BROWSER_PATH` 指定浏览器。AnyRouter 仍使用 CloakBrowser。

当 `CHECKIN_PROXY_URL` 是本地 mihomo mixed-port（例如 `http://127.0.0.1:7890`）时，AgentRouter 浏览器会自动改用同一端口的 SOCKS5，并禁用 QUIC；HTTP API 请求仍使用 HTTP 代理。

## 5. 手动验证

1. 打开仓库的 **Actions** 页面。
2. 选择 **AnyRouter 自动签到**。
3. 点击 **Run workflow**，先使用默认设置运行。
4. 展开运行日志，确认分别出现 `AnyRouter session` 和 `AgentRouter GitHub` 的处理结果。

如需排查浏览器登录过程，可在手动运行时将 `debug` 设为 `true`。调试截图会作为 workflow artifact 上传；截图可能包含账号页面，只在必要时使用并及时删除 artifact。

## 常见错误

### AnyRouter 返回 401

通常是 `session` 过期、复制了错误域名下的 Cookie，或 `api_user` 与 session 不匹配。重新登录 AnyRouter 后同时更新这两个值。

### AgentRouter 找不到 GitHub 登录或 OAuth 未完成

确认 GitHub Cookie 仍有效，导出的 Cookie 域名为 `github.com`，并建议配置 `PROXY_SUBSCRIPTION_URL`。不要把 AgentRouter 的站点 Cookie 放到 `github_cookies` 字段。

### `ANYROUTER_ACCOUNTS JSON 解析失败`

检查 Secret 是否包含完整的外层数组，使用双引号，删除注释、单引号和末尾逗号。
