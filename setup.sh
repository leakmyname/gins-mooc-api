#!/usr/bin/env bash
# 解压随仓库附带的数据：SQLite 库 + JSON 数据
set -e
cd "$(dirname "$0")"

if [ ! -f gins_mooc.db ]; then
  echo "解压 gins_mooc.db ..."
  gzip -dc release/gins_mooc.db.gz > gins_mooc.db
fi

if [ ! -d data ]; then
  echo "解压 data/ ..."
  tar -xzf release/data.tar.gz
fi

echo "OK: gins_mooc.db + data/"
