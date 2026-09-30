# Changelog

## v0.1.69
- 新增：Apple 登录双模式——默认 `APPLE_LOGIN_MODE=auto`（读 `apple_email.txt` 全自动）；可在自定义里改 `manual`，或命令行 `--apple-login-mode manual` 回退为浏览器手动登录后输入 `y`
- 优化：加歌间隔约 2.5 秒（`APPLE_SONG_INTERVAL_MIN/MAX`），缩短菜单内多余等待，提高效率
- 包含近期 Apple 自动登录链路：邮箱浅层填写、验证码页点「使用密碼登入」、空黑框关闭重试、登录态 JS 快判

## v0.1.58 – v0.1.68
- Apple 多账号自动登录与验证截断（`--apple-max-albums`）
- 登录调试截图、密码阶段坐标/UIA、空黑框处理与登录态识别等迭代修复
