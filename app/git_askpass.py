#!/usr/bin/env python3
"""Gitにだけ認証値を返す。認証値をURL、コマンド引数、ファイルに保存しない。"""

import os
import sys

key = "MCP_GIT_USERNAME" if "username" in sys.argv[1].lower() else "MCP_GIT_PASSWORD"
print(os.environ.get(key, ""))
