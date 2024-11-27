#!/bin/sh

SHARE_DIR=/share/srt_public

# 기존 /share/srt 디렉토리가 있으면 삭제합니다.
if [ -d "$SHARE_DIR" ]; then
    rm -rf "$SHARE_DIR"
    echo "[Info] 기존 디렉토리 삭제됨: $SHARE_DIR"
fi

# 새로운 /share/srt 디렉토리를 생성합니다.
mkdir -p $SHARE_DIR
mkdir -p $SHARE_DIR/templates
echo "[Info] 새로운 디렉토리 생성됨: $SHARE_DIR"

# 설정파일 생성 및 복사이동
/makeconf.sh
if /makeconf.sh; then
echo "[Info] makeconf.sh 실행 성공"
else
echo "[Error] makeconf.sh 실행 실패"
fi

# app.py와 index.html이 존재하는지 체크 후 이동
if [ -f /app.py ]; then
    mv /app.py $SHARE_DIR
    echo "[Info] /app.py를 $SHARE_DIR로 이동했습니다."
else
    echo "[Error] /app.py가 존재하지 않습니다."
fi

if [ -f /templates/index.html ]; then
    mv /templates/index.html $SHARE_DIR/templates/
    echo "[Info] /templates/index.html을 $SHARE_DIR/templates로 이동했습니다."
else
    echo "[Error] /templates/index.html이 존재하지 않습니다."
fi

echo "[Info] SRT 매크로 실행 중!"
cd $SHARE_DIR

# app.py 실행 (모든 인터페이스에서 수신하도록 설정)
if [ -f app.py ]; then
    python3 app.py --host 0.0.0.0 --port 5050
else
    echo "[Error] app.py가 존재하지 않아 실행할 수 없습니다."
fi

# 개발용 무한 루프
while true; do 
    echo "여전히 실행 중"; 
    sleep 100; 
done
