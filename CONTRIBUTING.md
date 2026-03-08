# Contributing to MediWise Health Suite

感谢您考虑为 MediWise Health Suite 做出贡献！

Thank you for considering contributing to MediWise Health Suite!

## 如何贡献 / How to Contribute

### 报告问题 / Reporting Issues

如果您发现 bug 或有功能建议：

If you find a bug or have a feature suggestion:

1. 检查 [Issues](https://github.com/your-username/mediwise-health-suite/issues) 是否已有相关问题
2. 如果没有，创建新 Issue，提供详细信息：
   - 问题描述
   - 复现步骤
   - 预期行为
   - 实际行为
   - 系统环境（OS、Python 版本等）

### 提交代码 / Submitting Code

1. **Fork 仓库**
   ```bash
   git clone https://github.com/your-username/mediwise-health-suite.git
   cd mediwise-health-suite
   ```

2. **创建分支**
   ```bash
   git checkout -b feature/your-feature-name
   # 或
   git checkout -b fix/your-bug-fix
   ```

3. **进行修改**
   - 遵循现有代码风格
   - 添加必要的注释
   - 更新相关文档

4. **测试**
   - 确保所有功能正常工作
   - 测试边界情况
   - 不要包含真实用户数据

5. **提交**
   ```bash
   git add .
   git commit -m "feat: add new feature" # 或 "fix: fix bug"
   ```

6. **推送并创建 Pull Request**
   ```bash
   git push origin feature/your-feature-name
   ```

### 代码规范 / Code Standards

#### Python 代码
- 使用 PEP 8 风格
- 函数和类添加 docstring
- 变量命名清晰易懂
- 避免硬编码路径和敏感信息

#### SKILL.md 文件
- 必须包含 YAML frontmatter（name, description）
- description 要清晰描述触发条件
- 使用中英文双语

#### 提交信息 / Commit Messages
使用语义化提交信息：
- `feat:` 新功能
- `fix:` Bug 修复
- `docs:` 文档更新
- `style:` 代码格式（不影响功能）
- `refactor:` 重构
- `test:` 测试相关
- `chore:` 构建/工具相关

### 隐私和安全 / Privacy and Security

⚠️ **重要提醒**：
- 不要提交包含真实用户数据的文件
- 不要提交 API keys、密码等敏感信息
- 不要提交 `.db` 或 `.sqlite` 文件
- 测试数据应使用匿名/虚构信息

### 文档 / Documentation

如果您的更改影响用户使用方式，请更新：
- README.md
- 相关 SKILL.md
- references/ 目录下的文档

### 许可证 / License

提交代码即表示您同意将代码以 MIT 许可证发布。

By submitting code, you agree to license your contribution under the MIT License.

## 行为准则 / Code of Conduct

- 尊重所有贡献者
- 保持友好和专业
- 接受建设性批评
- 关注项目最佳利益

## 问题？/ Questions?

如有疑问，请：
- 创建 Issue
- 发送邮件至 your-email@example.com

感谢您的贡献！🎉

Thank you for your contributions! 🎉
