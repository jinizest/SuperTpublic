FROM python:3.10

ENV LANG C.UTF-8

# Copy data for add-on
COPY run.sh makeconf.sh app.py /
COPY templates /templates

# 시스템 패키지 및 Python 패키지 설치
RUN apt-get update && apt-get install -y --no-install-recommends jq \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir Flask==2.0.1 Werkzeug==2.0.1 requests SRTrain urllib3==1.26.15

# 작업 디렉토리 설정
WORKDIR /share

# 실행 권한 부여
RUN chmod a+x /makeconf.sh
RUN chmod a+x /run.sh

# 실행 명령 설정
CMD [ "/run.sh" ]