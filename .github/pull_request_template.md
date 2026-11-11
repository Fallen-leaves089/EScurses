## 变更 / Summary

说明改了什么，以及用户能感知到的效果。

## 上游关系 / Upstream

- [ ] 改动遵循上游 API 和工程结构
- [ ] 如果偏离上游，已说明原因和后续同步方式

## 验证 / Verification

- [ ] `python -m compileall -q escurses.py tests`
- [ ] `python -m unittest discover -s tests -v`
- [ ] 未提交 `__pycache__`、`.pyc` 或虚拟环境
