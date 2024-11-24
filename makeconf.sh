#!/bin/bash

CONFIG_FILE=/data/options.json
CONFIG_srtapp=/share/srt/app.conf

if [ ! -f "$CONFIG_FILE" ]; then
    echo "[Error] 설정 파일을 찾을 수 없습니다: $CONFIG_FILE"
    exit 1
fi

echo "[Info] 설정 파일을 성공적으로 읽었습니다: $CONFIG_FILE"

> "$CONFIG_srtapp"
echo "[Info] $CONFIG_srtapp 파일을 초기화했습니다."

echo "[DEFAULT]" >> "$CONFIG_srtapp"

jq -r 'to_entries | .[] | select(.key != "Advanced") | "\(.key) = \(.value)"' "$CONFIG_FILE" | sed -e 's/false/False/g' -e 's/true/True/g' >> "$CONFIG_srtapp"

echo "[Info] 설정 파일 변환이 완료되었습니다: $CONFIG_srtapp"