from flask import Flask, render_template, request, jsonify, Response, session, flash
from SRT import SRT
import requests
from datetime import datetime
import time
import threading
import queue
import os
import logging
from logging.handlers import RotatingFileHandler
import configparser
import io

class CustomLogFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        return not any([
            'GET /heartbeat' in message,
            'POST /heartbeat' in message,
            'POST / HTTP/1.1' in message,
            'POST /stop HTTP/1.1' in message,
            'GET /stream/' in message,
            # 'GET /favicon.ico' in message,
            # 'POST /stop' in message
        ])

# Werkzeug 로거에 필터 적용
logging.getLogger("werkzeug").addFilter(CustomLogFilter())


def get_config(key, default=None):
    config = configparser.ConfigParser()
    config_file = '/share/srt_public/app.conf'
    if os.path.exists(config_file):
        config.read(config_file)
        try:
            return config.get('DEFAULT', key)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return default
    else:
        logging.error(f"설정 파일을 찾을 수 없습니다: {config_file}")
        return default

app = Flask(__name__)

SECRET_KEY = get_config('secret_key', 'vmffktmzm!@#')
app.secret_key = SECRET_KEY  # 보안설정 안전한 랜덤

# 로그 디렉토리 생성
log_dir = '/share/srt_public/logs'
os.makedirs(log_dir, exist_ok=True)



global messages, stop_reservation, output_queue, user_loggers
messages = {}
stop_reservation = {}
output_queue = {}
user_loggers = {}

# 설정 값 가져오기
SRT_ID = get_config('srt_id', '')
SRT_PASSWORD = get_config('srt_password', '')
TELEGRAM_BOT_TOKEN = get_config('telegram_bot_token', '')
TELEGRAM_CHAT_ID = get_config('telegram_chat_id', '')
PHONE_NUMBER = get_config('phone_number', '')

def get_user_logger(user_id):
    if user_id not in user_loggers:
        logger = logging.getLogger(f'user_{user_id}')
        logger.setLevel(logging.INFO)
        try:
            log_file = os.path.join('/share/srt_public/logs', f'user_{user_id}.log')
            handler = RotatingFileHandler(log_file, maxBytes=10000, backupCount=1)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        except Exception as e:
            print(f"로그 파일 생성 중 오류 발생: {e}")
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)
        user_loggers[user_id] = logger
    return user_loggers[user_id]

def send_telegram_message(bot_token, chat_id, message):
    if bot_token and chat_id:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": 'SRTrain Rev \n' + message + ' \n@' + datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            logging.info("메시지가 성공적으로 전송되었습니다.")
        else:
            logging.error(f"메시지 전송에 실패했습니다. 상태 코드: {response.status_code}")

def attempt_reservation(user_id, sid, spw, dep_station, arr_station, date, time_start, time_end, phone_number, enable_telegram, bot_token, chat_id):
    logger = get_user_logger(user_id)
    logger.info(f'예약 프로세스 시작 (사용자 ID: {user_id})')
    try:
        srt = SRT(sid, spw, verbose=False)
        trains = srt.search_train(dep_station, arr_station, date, time_start, time_end, available_only=False)
        while not stop_reservation.get(user_id, False):
            try:


                message = '예약시도.....' + ' @' + datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                logger.info(message)
                output_queue[user_id].put(message)
                time.sleep(2)

               
                if 'Expecting value' in str(trains):
                    message = 'Expecting value 오류'
                    logger.error(message)
                    output_queue[user_id].put(message)
                    messages[user_id].append(message)
                    continue

                # for train in trains: #예매 기차 출력
                #     logger.info(str(train))
                #     output_queue[user_id].put(str(train))

                for train in trains:
                    if stop_reservation.get(user_id, False):
                        break
                    try:
                        srt.reserve_standby(train)
                        srt.reserve_standby_option_settings(phone_number, True, True)
                        success_message = f"SRT 예약 대기 완료 {train}"
                        logger.info(success_message)
                        messages[user_id].append(success_message)
                        output_queue[user_id].put(success_message)
                        if enable_telegram:
                            send_telegram_message(bot_token, chat_id, success_message)
                        logger.info("예약 성공했지만 계속 진행합니다.")
                        flash("열차 예매에 성공했습니다!", "success")
                        break
                    except Exception as e:
                        error_message = f"열차 {train}에 대한 오류 발생: {e}"
                        logger.error(error_message)
                        output_queue[user_id].put(error_message)
                        messages[user_id].append(error_message)
                        if '비밀번호' in str(e) or '심각한 오류' in str(e):
                            output_queue[user_id].put("PASSWORD_ERROR")
                            stop_reservation[user_id] = True
                            break
                
                if user_id not in client_connections:
                    logger.info(f"클라이언트 연결이 끊어졌습니다. (사용자 ID: {user_id})")
                    break

            except Exception as e:
                error_message = f"메인 루프에서 오류 발생: {e}"
                logger.info(error_message)
                output_queue[user_id].put(error_message)
                messages[user_id].append(error_message)
                if '사용자가 많아 접속이 원활하지 않습니다.' in str(e):
                    time.sleep(5)
                    srt = SRT(sid, spw, verbose=False)
                    continue
                if enable_telegram:
                    send_telegram_message(bot_token, chat_id, error_message)
                if '비밀번호' in str(e) or '심각한 오류' in str(e):
                    output_queue[user_id].put("CRITICAL_ERROR")
                    stop_reservation[user_id] = True
                    break

            time.sleep(5)
            srt = SRT(sid, spw, verbose=False)

    except Exception as main_e:
        critical_error = f"MACRO 중지, 오류 발생: {main_e}"
        logger.info(critical_error)
        if '비밀번호' in str(main_e):
            error_message = str(main_e)
            output_queue[user_id].put("PASSWORD_ERROR")
        else:
            output_queue[user_id].put(critical_error)
        output_queue[user_id].put("CRITICAL_ERROR")
        messages[user_id].append(critical_error)
        stop_reservation[user_id] = True
        if enable_telegram:
            send_telegram_message(bot_token, chat_id, critical_error)

    finally:
        if 'srt' in locals():
            srt.logout()
        cleanup_reservation(user_id)

    return messages[user_id]


# -------------------- FLASK -----------------------------#


client_connections = {}

@app.route('/heartbeat', methods=['POST'])
def heartbeat():
    user_id = request.remote_addr
    client_connections[user_id] = time.time()
    return 'OK'


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        user_id = request.remote_addr
        if user_id in stop_reservation and not stop_reservation[user_id]:
            return jsonify({'message': '이미 예약 프로세스가 실행 중입니다.'})
        
        stop_reservation[user_id] = False
        messages[user_id] = []
        output_queue[user_id] = queue.Queue()
        
        sid = request.form.get('sid', SRT_ID)
        spw = request.form.get('spw', SRT_PASSWORD)
        dep_station = request.form['dep_station']
        arr_station = request.form['arr_station']
        if dep_station == "direct":
            dep_station = request.form['customDepStation']
        if arr_station == "direct":
            arr_station = request.form['customArrStation']
        date = request.form['date'].replace("-", "")
        start_time = f"{request.form['start_hour']}{request.form['start_minute']}00"
        end_time = f"{request.form['end_hour']}{request.form['end_minute']}00"
        phone_number = f"{request.form['phone_part1']}-{request.form['phone_part2']}-{request.form['phone_part3']}"
        enable_telegram = 'enable_telegram' in request.form
        bot_token = request.form.get('bot_token', TELEGRAM_BOT_TOKEN)
        chat_id = request.form.get('chat_id', TELEGRAM_CHAT_ID)
        
        thread = threading.Thread(target=attempt_reservation, args=(user_id, sid, spw, dep_station, arr_station, date, start_time, end_time, phone_number, enable_telegram, bot_token, chat_id))
        thread.start()
        
        return jsonify({'message': f'예약 프로세스가 시작되었습니다. (사용자 ID: {user_id})'})
    
    default_values = {
        'srt_id': SRT_ID,
        'srt_password': SRT_PASSWORD,
        'telegram_bot_token': TELEGRAM_BOT_TOKEN,
        'telegram_chat_id': TELEGRAM_CHAT_ID,
        'phone_number': PHONE_NUMBER
    }
    return render_template('index.html', **default_values)

@app.route('/stop', methods=['POST'])
def stop():
    user_id = request.remote_addr
    stop_reservation[user_id] = True
    return jsonify({'message': '예약 프로세스가 중단되었습니다.'})

@app.route('/stream/<user_id>')
def stream(user_id):
    def generate():
        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        formatter = logging.Formatter('%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        handler.setFormatter(formatter)
        logging.getLogger().addHandler(handler)
        last_timestamp = datetime.now()

        while True:
            log_stream.seek(0)
            log_content = log_stream.read()
            log_stream.truncate(0)
            log_stream.seek(0)

            if log_content:
                log_lines = log_content.strip().split('\n')
                new_logs = []
                for line in log_lines:
                    try:
                        timestamp_str = line.split(' - ')[0]
                        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S.%f')
                        if timestamp > last_timestamp and user_id in line:
                            new_logs.append(line)
                            last_timestamp = timestamp
                    except (ValueError, IndexError):
                        continue

                if new_logs:
                    new_logs.reverse()
                    newline = '\n'
                    yield f"data: {newline.join(new_logs)}\n\n"
            else:
                try:
                    message = output_queue[user_id].get_nowait()
                    if message == "PASSWORD_ERROR":
                        yield f"data: PASSWORD_ERROR\n\n"
                    else:
                        yield f"data: {message}\n\n"
                except (KeyError, queue.Empty):
                    time.sleep(0.1)

    return Response(generate(), mimetype='text/event-stream')


def cleanup_reservation(user_id):
    logger = get_user_logger(user_id)
    logger.info(f"클라이언트 연결 종료 확인. 정리 작업 시작 (사용자 ID: {user_id})")
    
    if user_id in stop_reservation:
        stop_reservation[user_id] = True
        logger.info(f"예약 프로세스 중지 (사용자 ID: {user_id})")
    
    if user_id in output_queue:
        output_queue[user_id].put("CONNECTION_LOST")
        logger.info(f"클라이언트에 연결 종료 메시지 전송 (사용자 ID: {user_id})")
    
    if user_id in client_connections:
        del client_connections[user_id]
        logger.info(f"클라이언트 연결 정보 삭제 (사용자 ID: {user_id})")
    
    logger.info(f"정리 작업 완료 (사용자 ID: {user_id})")

def check_client_connections():
    while True:
        time.sleep(15)  # 15초마다 확인
        current_time = time.time()
        for user_id, last_activity in list(client_connections.items()):
            if current_time - last_activity > 30:  # 30초 이상 활동이 없으면
                logger = get_user_logger(user_id)
                logger.info(f"클라이언트 비활성 감지. 정리 작업 시작 (사용자 ID: {user_id})")
                cleanup_reservation(user_id)
                client_connections.pop(user_id, None)  # KeyError 방지
                logger.info(f"클라이언트 연결 정보 제거 완료 (사용자 ID: {user_id})")

# 연결 확인 스레드 시작
threading.Thread(target=check_client_connections, daemon=True).start()

if __name__ == '__main__':
    log_level = get_config('LOG_LEVEL', 'INFO').upper()
    logging.basicConfig(
        format='%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=getattr(logging, log_level)
    )
    
    logger = logging.getLogger(__name__)
    try:
        port = int(get_config('PORT', 5050))
        logger.info(f"Starting SRT application on port {port}")
        app.run(host='0.0.0.0', port=port)
    except Exception as e:
        logger.error(f"Error starting application: {e}")
    
    while True:
        time.sleep(30)