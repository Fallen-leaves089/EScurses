# 分支与上游同步

本仓库是 [KID194/EScurses](https://github.com/KID194/EScurses) 的 fork。库的功能方向、API 和上游发布以原作者仓库为准；fork 只增加测试、CI 和仓库维护方面的最小改进。

## 长期分支

- `main`：唯一长期分支，按上游 `main` 同步，必须保持可测试。
- 不设长期 `develop` 分支。
- 不强制推送 `main`，不删除已发布 tag。

## 短分支

从 `main` 创建，完成后通过 Pull Request 回到 `main`：

- `feat/<topic>`：功能；
- `fix/<topic>`：缺陷修复；
- `docs/<topic>`：文档；
- `test/<topic>`：测试；
- `chore/<topic>`：CI、构建和仓库维护；
- `upstream/<topic>`：准备提交给上游的修复，必须从 `upstream/main` 创建，上游 PR 合并或关闭后删除。

合并方式使用 squash merge，合并后自动删除 head 分支。

## 上游 PR

- `fix/core-terminal-runtime` 对应上游 PR #4；在作者合并或关闭前保留，不把 fork 维护提交混入该分支。
- 本地 `review-pr-1/2/3` 是上游 PR #1/#2/#3 的只读审查快照，不上传；只有对应 PR 关闭后才清理。

## PR 门禁

- GitHub Actions 的 `test (ubuntu-latest)` 和 `test (windows-latest)` 必须通过；
- 本地至少运行 `python -m compileall -q escurses.py tests` 和 `python -m unittest discover -s tests -v`；
- 不提交 `__pycache__`、`.pyc`、虚拟环境或其他生成物；
- 用户可见 API 变化同步更新 `README-en.md`、`README-zh.md` 和 changelog。

