# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/afrendeiro/agentlog/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                         |    Stmts |     Miss |   Cover |   Missing |
|----------------------------- | -------: | -------: | ------: | --------: |
| src/agentlog/\_\_init\_\_.py |        0 |        0 |    100% |           |
| src/agentlog/claude.py       |       89 |        5 |     94% |45-47, 49, 75 |
| src/agentlog/cli.py          |      277 |       35 |     87% |99, 101, 103, 125, 148, 153-155, 164, 170-174, 190, 204, 216, 227-228, 232-238, 242-245, 251, 259, 284, 351-354, 360 |
| src/agentlog/common.py       |       81 |        3 |     96% |16, 103, 119 |
| src/agentlog/opencode.py     |       69 |        1 |     99% |        91 |
| src/agentlog/render.py       |       57 |        2 |     96% |    31, 71 |
| src/agentlog/store.py        |       32 |        0 |    100% |           |
| src/agentlog/summarize.py    |       42 |        0 |    100% |           |
| src/agentlog/web.py          |       66 |        6 |     91% |   178-183 |
| **TOTAL**                    |  **713** |   **52** | **93%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/afrendeiro/agentlog/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/afrendeiro/agentlog/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/afrendeiro/agentlog/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/afrendeiro/agentlog/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Fafrendeiro%2Fagentlog%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/afrendeiro/agentlog/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.